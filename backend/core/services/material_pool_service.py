"""素材池装配（从分镜 agents 层迁入）

- 素材池 ID 解析（lookbook_lb_* 核心素材 / mat_* 分集素材图）
- 素材池列表（核心素材 story 级 + 按集分组素材，不跨 story）
- 上传参考图路径校验（拒绝越出 static/uploads 的路径穿越）
- 分镜删除前素材回收（重新选集/删除视频会话时，素材图保留在库可复用）
"""
import logging
import shutil
from pathlib import Path

from backend.core.errors import WorkflowError
from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.workspace_store import DIR_STORYBOARDS, WorkspaceStore
from backend.core.services.workspace_sections import episode_number
from backend.core.utils.path_utils import resolve_project_path

logger = logging.getLogger(__name__)


class MaterialPoolService:
    """素材池读取与校验"""

    def __init__(
        self,
        store: WorkspaceStore,
        scm: ScriptManager,
        error_cls: type[WorkflowError] = WorkflowError,
    ):
        self.store = store
        self.scm = scm
        self.error = error_cls

    def resolve_pool_image(self, script_session_id: str, image_id: str) -> dict:
        """解析素材池 ID → {image_id, image_path, description}；不存在/跨 story/未完成抛业务异常

        ID 规则：lookbook_lb_* 核心素材（script_context.fetch_lookbook_images 的形态）/ mat_* 分集素材图
        """
        if image_id.startswith("lookbook_"):
            row = self.scm.get_lookbook(image_id[len("lookbook_"):])
        else:
            row = self.scm.get_episode_material(image_id)
        if not row or row.get("script_session_id") != script_session_id:
            raise self.error(f"素材图不存在或不属于当前剧本: {image_id}")
        if not row.get("image_path"):
            raise self.error(f"素材图尚未生成完成: {image_id}")
        return {
            "image_id": image_id,
            "image_path": row["image_path"],
            "description": row.get("description", ""),
        }

    def list_pool(self, script_session_id: str, episode_id: str) -> dict:
        """选择弹窗素材池：核心素材（story 级）+ 本集素材 + 其他集素材（不跨 story）"""
        groups = []
        lookbook = [
            {"image_id": m["image_id"], "image_path": m["image_path"], "description": m["description"]}
            for m in self._fetch_lookbook_images(script_session_id)
        ]
        if lookbook:
            groups.append({"key": "lookbook", "label": "核心素材", "materials": lookbook})

        episode_titles = {e["episode_id"]: (e.get("title") or "") for e in self.store.list_episodes(script_session_id)}
        by_episode: dict[str, list[dict]] = {}
        for row in self.scm.list_episode_materials(script_session_id, task_status="completed"):
            if not row.get("image_path"):
                continue
            by_episode.setdefault(row["episode_id"], []).append({
                "image_id": row["image_id"],
                "image_path": row["image_path"],
                "description": row.get("description", ""),
                "title": row.get("title", ""),
            })
        for eid in sorted(by_episode, key=episode_number):
            label = f"本集素材（{eid}《{episode_titles.get(eid, '')}》）" if eid == episode_id \
                else f"{eid}《{episode_titles.get(eid, '')}》素材"
            groups.append({
                "key": "current" if eid == episode_id else f"episode_{eid}",
                "label": label,
                "episode_id": eid,
                "materials": by_episode[eid],
            })
        return {"groups": groups}

    def _fetch_lookbook_images(self, script_session_id: str) -> list[dict]:
        """取已完成的核心素材（素材池形态，image_id 带 lookbook_ 前缀）"""
        return [
            {
                "image_id": f"lookbook_{row['image_id']}",
                "image_path": row["image_path"],
                "description": row["description"],
            }
            for row in self.scm.list_lookbook(script_session_id, task_status="completed")
            if row.get("image_path")
        ]

    def delete_material(self, script_session_id: str, image_id: str) -> bool:
        """删除分集素材图：DB 记录 + 本地归档文件（http 外链无文件可删）

        素材池分镜文件中的引用不在清理范围（与核心素材删除行为一致）。
        """
        row = self.scm.get_episode_material(image_id)
        if not row or row.get("script_session_id") != script_session_id:
            raise self.error(f"素材图不存在或不属于当前剧本: {image_id}", status_code=404)
        ok = self.scm.delete_episode_material(script_session_id, image_id)
        image_path = row.get("image_path") or ""
        if ok and image_path and not image_path.startswith(("http://", "https://")):
            try:
                resolve_project_path(image_path).unlink(missing_ok=True)
            except OSError:
                pass  # 文件清理失败不阻断记录删除
        return ok

    def validate_reference_paths(self, reference_paths: list[str]) -> list[str]:
        """上传参考图路径校验：resolve 后必须仍在 static/uploads 目录内（拒绝 ../.. 路径穿越）"""
        uploads_root = resolve_project_path("static/uploads").resolve()
        for path in reference_paths:
            resolved = resolve_project_path(path).resolve()
            if uploads_root != resolved.parent and uploads_root not in resolved.parents:
                raise self.error(f"非法的参考图路径: {path}")
            if not resolved.is_file():
                raise self.error(f"参考图文件不存在: {path}")
        return reference_paths

    def recycle_segment_materials(
        self, script_session_id: str, episode_id: str, video_session_id: str,
    ) -> int:
        """删除分镜目录前回收素材：分镜引用的未登记图补登记进 episode_material_images

        重新选集/删除视频会话时调用——分镜脚本将删，但素材图宝贵：
        登记后素材管理可见、素材池可复用、可人工删除。
        Returns: 新登记的素材张数
        """
        sb = self.store.read_storyboard(script_session_id, episode_id, video_session_id)
        # 已登记路径集合：md 引用的旧 ID（如已删除的旧轮次 lb_*）查不到行，
        # 按路径去重防止同一文件被多分镜/多次回收重复登记
        existing = {
            r.get("image_path") for r in self.scm.list_episode_materials(script_session_id)
            if r.get("image_path")
        }
        count = 0
        seen: set[str] = set()
        for seg in (sb or {}).get("segments") or []:
            for ref in seg.get("reference_images") or []:
                path = str((ref or {}).get("image_path") or "")
                image_id = str((ref or {}).get("image_id") or "")
                if not path or path in seen or path in existing or path.startswith(("http://", "https://")):
                    continue
                seen.add(path)
                # 已在库（核心素材 lb_* / 分集素材 mat_*）→ 无需回收
                norm = image_id[len("lookbook_"):] if image_id.startswith("lookbook_") else image_id
                if norm.startswith("lb_") and self.scm.get_lookbook(norm):
                    continue
                if norm.startswith("mat_") and self.scm.get_episode_material(norm):
                    continue
                if not resolve_project_path(path).is_file():
                    continue
                description = str((ref or {}).get("description") or "").strip()
                title = description[:40] or Path(path).stem
                row = self.scm.insert_episode_material(
                    script_session_id, episode_id, title=title, description=description,
                    task_status="completed", meta={"origin": "recycled"},
                )
                self.scm.update_episode_material(row["image_id"], {"image_path": path})
                count += 1
        return count

    def remove_video_storyboard(self, video_session_id: str, sm) -> int:
        """删除视频会话的全部分镜目录（先回收素材再删目录）；返回清理的目录数

        不依赖 sessions 表的 script_session_id（历史视频会话该列常为空），
        直接按 vs-{sid8} 在全部 story 下定位；素材图与 DB 素材登记不受影响。
        """
        n = 0
        for vs in sorted(self.store.root.glob(f"*/{DIR_STORYBOARDS}/*/vs-{video_session_id[:8]}")):
            story_dir = vs.parent.parent.parent
            sid8 = story_dir.name.rsplit("-", 1)[-1]
            episode_id = vs.parent.name
            # sid8 → 全量 script_session_id（回收登记需关联 DB 的 script_session_id）
            script_sid = next(
                (s["session_id"] for s in sm.list_sessions(workflow_type="script")
                 if s["session_id"].startswith(sid8)),
                "",
            )
            if script_sid:
                recycled = self.recycle_segment_materials(script_sid, episode_id, video_session_id)
                if recycled:
                    logger.info(f"[素材回收] 回收 {recycled} 张分镜素材（{story_dir.name}/{episode_id}）")
            shutil.rmtree(vs, ignore_errors=True)
            n += 1
        return n
