"""素材管理服务：全局素材列表 / 引用保护删除 / 孤儿文件扫描

素材三来源与引用形态：
- 生成图：lookbook_images / episode_material_images 两表（image_path → static/images/**）；
  引用在 workspace 实体 md（lookbook_image_id，形如 lb_xxx）与分镜 md
 （reference_images[].image_id，形如 lookbook_lb_xxx / mat_xxx）的 frontmatter
- 上传参考图：static/uploads/**，无持久引用记录（仅生图请求的瞬时参数），视为未引用
- 视频：static/videos/**，引用只存在于 step_results.result_data JSON
 （generated_videos[].video_path / final_video.video_path / _old_* 备份字段）

引用索引每次请求实时构建（素材/文件量级数百，毫秒级），不建缓存。
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

import frontmatter

from backend.core.errors import WorkflowError
from backend.core.persistence.workspace_store import DIR_STORYBOARDS
from backend.core.services.step_payload import script_title
from backend.core.utils.path_utils import resolve_project_path

logger = logging.getLogger(__name__)

# 素材根目录（相对项目根，与 path_utils 的 IMAGE_SAVE_DIR/VIDEO_SAVE_DIR 一致的字符串形态）
IMAGES_ROOT = "static/images"
VIDEOS_ROOT = "static/videos"
UPLOADS_ROOT = "static/uploads"

# 素材类型白名单
KINDS = ("lookbook", "episode", "upload", "video")

# 上传文件保护窗口：mtime 距今不足该秒数的上传文件不进孤儿列表（生图任务可能正在使用）
UPLOAD_PROTECT_SECONDS = 3600

_REMOTE_PREFIXES = ("http://", "https://")


def _is_remote(path: str) -> bool:
    return path.startswith(_REMOTE_PREFIXES)


def _normalize_image_id(image_id: str) -> str:
    """分镜引用的 lookbook_lb_xxx 归一化为 DB 主键 lb_xxx"""
    return image_id[len("lookbook_"):] if image_id.startswith("lookbook_") else image_id


def _file_size(path: str) -> int:
    """本地文件大小（http 外链/文件缺失为 0）"""
    if not path or _is_remote(path):
        return 0
    try:
        return resolve_project_path(path).stat().st_size
    except OSError:
        return 0


def _scan_files(root: str) -> list[tuple[str, int, float]]:
    """扫描素材目录下全部文件：[(素材路径 key, size, mtime 时间戳)]

    key 形态 = f"{root}/{相对子路径}"（生产为 static/images/xx.png，与 DB/md 存储形态一致；
    测试可将 root 常量替换为绝对路径以注入临时目录）。
    """
    base = resolve_project_path(root)
    if not base.is_dir():
        return []
    files = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            rel = path.resolve().relative_to(base.resolve()).as_posix()
        except (OSError, ValueError):
            continue
        files.append((f"{root}/{rel}", stat.st_size, stat.st_mtime))
    return files


def _iter_segment_docs(story: Path):
    """遍历 story 下全部分镜 md，yield (episode_id, frontmatter)"""
    board = story / DIR_STORYBOARDS
    if not board.is_dir():
        return
    for path in sorted(board.glob("**/seg_*.md")):
        try:
            post = frontmatter.load(str(path))
        except Exception as e:
            logger.warning(f"[素材管理] 分镜文件解析失败，跳过: {path} ({e})")
            continue
        # 目录形态 04-storyboards/{episode_id}/vs-*/seg_NN-*.md
        yield path.parent.parent.name, post.metadata or {}


def _script_titles(store, sm) -> dict[str, str]:
    """存活剧本会话 → 展示名"""
    titles = {}
    for sess in sm.list_sessions(workflow_type="script"):
        sid = sess["session_id"]
        if store.story_dir(sid):
            titles[sid] = script_title(store, sid) or f"剧本 {sid[:8]}"
    return titles


def build_image_reference_index(store, sm) -> dict[str, list[dict]]:
    """图片引用索引：归一化 image_id → 引用位置列表（实体 / 分镜，仅存活剧本会话）"""
    index: dict[str, list[dict]] = {}
    for sid, title in _script_titles(store, sm).items():
        story = store.story_dir(sid)
        if not story:
            continue
        for entity in store.list_entities(sid):
            image_id = entity.get("lookbook_image_id") or ""
            if image_id:
                index.setdefault(_normalize_image_id(image_id), []).append({
                    "ref_type": "entity",
                    "script_session_id": sid,
                    "script_title": title,
                    "entity_id": entity.get("entity_id", ""),
                    "entity_name": entity.get("name", ""),
                })
        for episode_id, meta in _iter_segment_docs(story):
            for ref in meta.get("reference_images") or []:
                image_id = _normalize_image_id(str((ref or {}).get("image_id") or ""))
                if image_id:
                    index.setdefault(image_id, []).append({
                        "ref_type": "segment",
                        "script_session_id": sid,
                        "script_title": title,
                        "episode_id": episode_id,
                        "segment_index": meta.get("index"),
                        "segment_title": meta.get("title", ""),
                    })
    return index


def _collect_strings(obj):
    """递归收集 JSON 结构中的全部字符串值（视频路径可能藏在任意层级/备份字段）"""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _collect_strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _collect_strings(value)


def build_video_reference_index(sm, store) -> dict[str, list[dict]]:
    """视频引用索引：相对 posix 路径 → 引用它的视频会话列表（来自 step_results 全表）"""
    video_sessions = {s["session_id"]: s for s in sm.list_sessions(workflow_type="video")}
    titles = _script_titles(store, sm)
    index: dict[str, list[dict]] = {}
    for row in sm.list_all_step_results():
        try:
            data = json.loads(row["result_data"])
        except (ValueError, TypeError):
            continue
        sid = row["session_id"]
        sess = video_sessions.get(sid) or {}
        owner_title = titles.get(sess.get("script_session_id") or "", "")
        for value in _collect_strings(data):
            raw = value.split("?")[0]
            # 兼容带前导 / 的路径形态（/static/videos/x.mp4 → static/videos/x.mp4）
            rel = raw.lstrip("/") if raw.lstrip("/").startswith(VIDEOS_ROOT) else raw
            if not rel.startswith(VIDEOS_ROOT):
                continue
            refs = index.setdefault(rel, [])
            if not any(r["video_session_id"] == sid for r in refs):  # 同会话多段引用同一视频去重
                refs.append({"video_session_id": sid, "script_title": owner_title})
    return index


def _image_reference_paths(store, sm, scm) -> set[str]:
    """被引用的本地图片路径集合 = 两表全部 image_path ∪ workspace md 中的 image_path

    按路径判定（而非 ID）：DB 行已删但分镜/实体 md 仍引用的文件不算孤儿。
    """
    paths = set()
    for row in [*scm.list_completed_lookbooks(), *scm.list_completed_episode_materials()]:
        path = row.get("image_path") or ""
        if path and not _is_remote(path):
            paths.add(path)
    return paths | _workspace_image_paths(store, sm)


def _workspace_image_paths(store, sm) -> set[str]:
    """workspace 实体/分镜 md frontmatter 中引用的本地图片路径集合（仅存活剧本会话）"""
    paths = set()
    for sess in sm.list_sessions(workflow_type="script"):
        sid = sess["session_id"]
        story = store.story_dir(sid)
        if not story:
            continue
        for entity in store.list_entities(sid):
            path = entity.get("lookbook_image_path") or ""
            if path and not _is_remote(path):
                paths.add(path)
        for _episode_id, meta in _iter_segment_docs(story):
            for ref in meta.get("reference_images") or []:
                path = str((ref or {}).get("image_path") or "")
                if path and not _is_remote(path):
                    paths.add(path)
    return paths


def list_materials(kind: str, store, sm, scm) -> dict:
    """全局素材列表（kind: lookbook / episode / upload / video）"""
    if kind not in KINDS:
        raise WorkflowError(f"未知素材类型: {kind}（可选 {list(KINDS)}）")

    if kind in ("lookbook", "episode"):
        titles = _script_titles(store, sm)
        refs = build_image_reference_index(store, sm)
        rows = scm.list_completed_lookbooks() if kind == "lookbook" else scm.list_completed_episode_materials()
        items = []
        for row in rows:
            path = row.get("image_path") or ""
            item_refs = refs.get(row["image_id"], [])
            sid = row.get("script_session_id", "")
            item = {
                "image_id": row["image_id"],
                "image_path": path,
                "is_remote": _is_remote(path),
                "description": row.get("description", ""),
                "script_session_id": sid,
                "script_title": titles.get(sid, "已删除剧本"),
                "created_at": row.get("created_at", ""),
                "size": _file_size(path),
                "reference_count": len(item_refs),
                "references": item_refs,
            }
            if kind == "lookbook":
                item["entity_id"] = row.get("entity_id", "")
            else:
                item["episode_id"] = row.get("episode_id", "")
                item["title"] = row.get("title", "")
            items.append(item)
        items.sort(key=lambda x: x["created_at"], reverse=True)
        return {"kind": kind, "items": items, "total": len(items)}

    if kind == "upload":
        items = [
            {"path": rel, "name": Path(rel).name, "size": size, "mtime": mtime, "reference_count": 0}
            for rel, size, mtime in _scan_files(UPLOADS_ROOT)
        ]
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return {"kind": kind, "items": items, "total": len(items)}

    # video
    refs = build_video_reference_index(sm, store)
    items = []
    for rel, size, mtime in _scan_files(VIDEOS_ROOT):
        owners = refs.get(rel, [])
        items.append({
            "path": rel,
            "name": Path(rel).name,
            "size": size,
            "mtime": mtime,
            "reference_count": len(owners),
            "references": owners,
            "script_title": owners[0]["script_title"] if owners else "",
        })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return {"kind": kind, "items": items, "total": len(items)}


def delete_image(image_id: str, store, sm, scm) -> dict:
    """删除生成图：引用中拒绝；删 DB 行 +（无其他行共享时）磁盘文件"""
    if image_id.startswith("lb_"):
        row, is_lookbook = scm.get_lookbook(image_id), True
    elif image_id.startswith("mat_"):
        row, is_lookbook = scm.get_episode_material(image_id), False
    else:
        raise WorkflowError(f"无法识别的素材 ID: {image_id}")
    if not row:
        raise WorkflowError(f"素材不存在: {image_id}", status_code=404)

    refs = build_image_reference_index(store, sm).get(image_id, [])
    if refs:
        raise WorkflowError(f"素材正被 {len(refs)} 处引用（分镜/实体），请先解除引用", status_code=409)

    sid = row["script_session_id"]
    if is_lookbook:
        scm.delete_lookbook(sid, image_id)
    else:
        scm.delete_episode_material(sid, image_id)

    # 文件清理：素材库导入会产生多行指向同一文件，仅当无其他行共享时才删
    path = row.get("image_path") or ""
    file_deleted = False
    if path and not _is_remote(path):
        sharing = [
            r for r in [*scm.list_completed_lookbooks(), *scm.list_completed_episode_materials()]
            if r.get("image_path") == path
        ]
        if not sharing:
            try:
                resolve_project_path(path).unlink(missing_ok=True)
                file_deleted = True
            except OSError as e:
                logger.warning(f"[素材管理] 文件清理失败（记录已删）: {path} ({e})")
    return {"deleted": True, "file_deleted": file_deleted, "image_id": image_id}


def _locate_in_roots(resolved: Path) -> Optional[tuple[str, str]]:
    """定位文件所属素材目录：返回 (root 常量, 相对 posix 路径) 或 None（不在三目录内）"""
    for root in (IMAGES_ROOT, VIDEOS_ROOT, UPLOADS_ROOT):
        try:
            return root, resolved.relative_to(resolve_project_path(root).resolve()).as_posix()
        except ValueError:
            continue
    return None


def delete_files(paths: list[str], store, sm, scm) -> dict:
    """批量删除素材文件（孤儿清理 / 上传图 / 视频单删入口）

    安全校验：路径必须位于 static/{images,videos,uploads} 内；被引用的图片/视频拒删。
    """
    image_refs = _image_reference_paths(store, sm, scm)
    video_refs = set(build_video_reference_index(sm, store))
    deleted: list[str] = []
    failed: list[dict] = []
    for raw in paths:
        rel = (raw or "").strip()
        if not rel:
            continue
        try:
            resolved = resolve_project_path(rel).resolve()
            located = _locate_in_roots(resolved)
            if not located:
                failed.append({"path": rel, "reason": "路径不在素材目录内"})
                continue
            key = f"{located[0]}/{located[1]}"
            if key in image_refs:
                failed.append({"path": rel, "reason": "图片正被剧本引用"})
                continue
            if key in video_refs:
                failed.append({"path": rel, "reason": "视频正被工作流引用"})
                continue
            if not resolved.is_file():
                failed.append({"path": rel, "reason": "文件不存在"})
                continue
            resolved.unlink()
            deleted.append(key)
        except OSError as e:
            failed.append({"path": rel, "reason": str(e)})
    return {"deleted": deleted, "failed": failed}


def scan_orphans(store, sm, scm) -> dict:
    """孤儿文件扫描：static 三目录下无 DB 记录且无 workspace 引用的文件

    - images：不在「DB image_path ∪ md image_path」集合内
    - videos：不在 step_results 引用集合内
    - uploads：无持久引用记录，全部为候选；mtime 距今不足保护窗口的跳过（生图任务可能正在使用）
    """
    items: list[dict] = []

    image_refs = _image_reference_paths(store, sm, scm)
    for rel, size, mtime in _scan_files(IMAGES_ROOT):
        if rel not in image_refs:
            items.append({"path": rel, "kind": "image", "size": size, "mtime": mtime})

    video_refs = set(build_video_reference_index(sm, store))
    for rel, size, mtime in _scan_files(VIDEOS_ROOT):
        if rel not in video_refs:
            items.append({"path": rel, "kind": "video", "size": size, "mtime": mtime})

    now = time.time()
    for rel, size, mtime in _scan_files(UPLOADS_ROOT):
        if now - mtime < UPLOAD_PROTECT_SECONDS:
            continue
        items.append({"path": rel, "kind": "upload", "size": size, "mtime": mtime})

    items.sort(key=lambda x: x["size"], reverse=True)
    return {"items": items, "total": len(items), "total_size": sum(i["size"] for i in items)}
