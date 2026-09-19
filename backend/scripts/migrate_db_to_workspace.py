"""存量数据迁移：SQLite step_results/episodes/script_entities → workspace/ markdown 文件

用法（项目根执行）：
  .venv/bin/python backend/scripts/migrate_db_to_workspace.py --export   # DB → 文件（幂等，可重跑）
  .venv/bin/python backend/scripts/migrate_db_to_workspace.py --verify   # DB ↔ 文件逐键对账（差异非零退出）
  .venv/bin/python backend/scripts/migrate_db_to_workspace.py --cutover  # DB 瘦身（P6：备份后把 step_results 换薄 envelope）

约定：
- 时间戳不保真（文件时间戳自导出时刻起为新的权威）；--verify 不对比时间戳
- 留 DB 不迁：story_ideation 的 agent_session_id/messages、select_episode、generate_videos、
  lookbook/episode_material 任务表（非 markdown 内容，按改造方案保留在 DB）
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.session_manager import SCRIPT_STEPS, VIDEO_STEPS, SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore

# verify 时允许文件侧存在、DB 侧不存在的键（文件化新增的元数据/时间戳）
EPISODE_IGNORE_KEYS = {"edited", "created_at", "updated_at"}
ENTITY_IGNORE_KEYS = {"created_at", "updated_at"}
SEGMENT_IGNORE_KEYS = {"edited", "updated_at"}


def build_managers():
    sm_video = SessionManager(steps=VIDEO_STEPS)
    sm_script = SessionManager(steps=SCRIPT_STEPS)
    scm = ScriptManager()
    store = WorkspaceStore(session_manager=sm_script)
    return sm_video, sm_script, scm, store


def iter_script_sessions(sm_script: SessionManager):
    for info in sm_script.list_sessions(workflow_type="script"):
        yield info["session_id"]


def iter_video_sessions(sm_video: SessionManager):
    for info in sm_video.list_sessions(workflow_type="video"):
        yield info["session_id"]


# ==================== export ====================

def do_export() -> int:
    sm_video, sm_script, scm, store = build_managers()
    stats = {"stories": 0, "story_logic": 0, "outlines": 0, "entities": 0, "episodes": 0, "storyboards": 0, "skipped": 0}

    for sid in iter_script_sessions(sm_script):
        story = store.ensure_story(sid, title=sm_script.get_script_title(sid) or "")
        stats["stories"] += 1
        # 幂等：先清文件侧分集/实体，避免 DB 已删数据在文件残留（大纲与分镜不受影响）
        store.delete_story_content(sid)

        ideation = sm_script.get_step_result(sid, "story_ideation")
        if ideation and (ideation["result_data"].get("story_logic") or "").strip():
            store.write_story_logic(sid, ideation["result_data"]["story_logic"])
            stats["story_logic"] += 1

        outline = sm_script.get_step_result(sid, "story_outline")
        if outline:
            rd = outline["result_data"]
            store.write_outline(sid, rd.get("mindmap", ""), requirements=rd.get("requirements") or {},
                                edited=bool(rd.get("edited")))
            stats["outlines"] += 1

        for entity in scm.list_entities(sid):
            store.upsert_entity(
                sid, entity["entity_type"], entity["name"], entity["description"] or "",
                meta=entity.get("meta") or {}, entity_id=entity["entity_id"],
                create_if_missing=True,
            )
            if entity.get("lookbook_image_id"):
                store.set_entity_lookbook(
                    entity["entity_id"], entity["lookbook_image_id"], entity.get("lookbook_image_path", ""),
                )
            stats["entities"] += 1

        for episode in scm.list_episodes(sid):
            store.upsert_episode(sid, episode)
            stats["episodes"] += 1

    for vsid in iter_video_sessions(sm_video):
        selected = sm_video.get_step_result(vsid, "select_episode")
        outline = sm_video.get_step_result(vsid, "storyboard_outline")
        if not selected or not outline:
            continue  # 未选集或未生成分镜的会话无文件产物
        script_session_id = selected["result_data"].get("script_session_id", "")
        episode_id = selected["result_data"].get("episode_id", "")
        if not script_session_id or not sm_script.get_session(script_session_id):
            print(f"  ⚠ 跳过视频会话 {vsid[:8]}...：引用的剧本会话不存在")
            stats["skipped"] += 1
            continue
        rd = outline["result_data"]
        store.write_storyboard(
            script_session_id, episode_id, vsid,
            mindmap=rd.get("mindmap", ""), segments=rd.get("segments") or [],
            edited=bool(rd.get("edited")),
        )
        stats["storyboards"] += 1

    print(f"导出完成: {stats}")
    return 0


# ==================== verify ====================

def _diff_dict(source: str, label: str, db: dict, file: dict, ignore: set, diffs: list) -> None:
    for key in {k for k in db if k not in ignore}:
        if db.get(key) != file.get(key):
            diffs.append(f"{source} {label} 字段 {key}: DB={db.get(key)!r:.200} 文件={file.get(key)!r:.200}")


def do_verify() -> int:
    sm_video, sm_script, scm, store = build_managers()
    diffs: list[str] = []

    for sid in iter_script_sessions(sm_script):
        story = store.story_dir(sid)
        if not story:
            diffs.append(f"剧本会话 {sid[:8]}... 缺少 story 目录")
            continue

        ideation = sm_script.get_step_result(sid, "story_ideation")
        db_logic = (ideation["result_data"].get("story_logic") or "") if ideation else ""
        if db_logic.strip() and store.read_story_logic(sid) != db_logic:
            diffs.append(f"{sid[:8]}... story_logic 不一致")

        outline = sm_script.get_step_result(sid, "story_outline")
        file_outline = store.read_outline(sid)
        if outline and not file_outline:
            diffs.append(f"{sid[:8]}... 缺少 outline.md")
        elif outline and file_outline:
            rd = outline["result_data"]
            for key, ignore in (("mindmap", set()), ("edited", set()), ("requirements", set())):
                db_v, file_v = rd.get(key), file_outline.get(key)
                if key == "requirements" and not db_v:
                    db_v = {}
                if db_v != file_v:
                    diffs.append(f"{sid[:8]}... outline.{key} 不一致")

        for entity in scm.list_entities(sid):
            file_entity = store.get_entity(entity["entity_id"])
            if not file_entity:
                diffs.append(f"{sid[:8]}... 缺少实体 {entity['entity_id']}")
                continue
            _diff_dict(sid[:8], f"实体 {entity['entity_id']}", entity, file_entity, ENTITY_IGNORE_KEYS, diffs)

        for episode in scm.list_episodes(sid):
            file_ep = store.get_episode(sid, episode["episode_id"])
            if not file_ep:
                diffs.append(f"{sid[:8]}... 缺少分集 {episode['episode_id']}")
                continue
            _diff_dict(sid[:8], f"分集 {episode['episode_id']}", episode, file_ep, EPISODE_IGNORE_KEYS, diffs)

    for vsid in iter_video_sessions(sm_video):
        selected = sm_video.get_step_result(vsid, "select_episode")
        outline = sm_video.get_step_result(vsid, "storyboard_outline")
        if not selected or not outline:
            continue
        script_session_id = selected["result_data"].get("script_session_id", "")
        episode_id = selected["result_data"].get("episode_id", "")
        if not script_session_id or not sm_script.get_session(script_session_id):
            continue
        rd = outline["result_data"]
        file_sb = store.read_storyboard(script_session_id, episode_id, vsid)
        if not file_sb:
            diffs.append(f"视频会话 {vsid[:8]}... 缺少分镜目录")
            continue
        if rd.get("mindmap") != file_sb.get("mindmap"):
            diffs.append(f"视频会话 {vsid[:8]}... storyboard.mindmap 不一致")
        if bool(rd.get("edited")) != bool(file_sb.get("edited")):
            diffs.append(f"视频会话 {vsid[:8]}... storyboard.edited 不一致")
        db_segments = {s.get("index"): s for s in rd.get("segments") or []}
        file_segments = {s.get("index"): s for s in file_sb.get("segments") or []}
        if set(db_segments) != set(file_segments):
            diffs.append(f"视频会话 {vsid[:8]}... 分镜数量/索引不一致: DB={sorted(db_segments)} 文件={sorted(file_segments)}")
            continue
        for idx, db_seg in db_segments.items():
            _diff_dict(f"视频会话 {vsid[:8]}...", f"分镜 {idx}", db_seg, file_segments[idx], SEGMENT_IGNORE_KEYS, diffs)

    if diffs:
        print(f"发现 {len(diffs)} 处差异:")
        for d in diffs[:50]:
            print(f"  - {d}")
        if len(diffs) > 50:
            print(f"  ...（其余 {len(diffs) - 50} 处略）")
        return 1
    print("对账通过：DB 与工作区文件零差异")
    return 0


# ==================== cutover ====================

def _has_content_rows(sm_script: SessionManager, sm_video: SessionManager) -> bool:
    """检测 DB 是否仍存有未迁移的完整内容行（cutover 后 export/verify 必须失效）"""
    for sid in iter_script_sessions(sm_script):
        step = sm_script.get_step_result(sid, "story_outline")
        if step and "mindmap" in step["result_data"]:
            return True
    for vsid in iter_video_sessions(sm_video):
        step = sm_video.get_step_result(vsid, "storyboard_outline")
        if step and "segments" in step["result_data"]:
            return True
    return False


def do_cutover(purge_tables: bool) -> int:
    sm_video, sm_script, scm, store = build_managers()

    # 1. cutover 前置检查：必须先 export（文件齐全才可丢弃 DB 内容）
    missing = 0
    for sid in iter_script_sessions(sm_script):
        if sm_script.get_step_result(sid, "story_outline") and not store.read_outline(sid):
            print(f"  ✗ 剧本会话 {sid[:8]}... 的大纲未导出，请先运行 --export")
            missing += 1
    for vsid in iter_video_sessions(sm_video):
        step = sm_video.get_step_result(vsid, "storyboard_outline")
        if step and "segments" in step["result_data"]:
            selected = sm_video.get_step_result(vsid, "select_episode")
            if not selected or not store.read_storyboard(
                selected["result_data"].get("script_session_id", ""),
                selected["result_data"].get("episode_id", ""), vsid,
            ):
                print(f"  ✗ 视频会话 {vsid[:8]}... 的分镜未导出，请先运行 --export")
                missing += 1
    if missing:
        return 1

    # 2. 备份 DB（永不 DROP 表；备份文件可整体回滚）
    import shutil
    import time as _time
    backup = f"data/sessions.db.bak-{_time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2("data/sessions.db", backup)
    print(f"已备份数据库 → {backup}")

    stats = {"outlines": 0, "storyboards": 0, "episodes": 0, "entities": 0}

    # 3. story_outline / storyboard_outline 内容行 → 薄 envelope（保留 _success/_cancelled）
    for sid in iter_script_sessions(sm_script):
        step = sm_script.get_step_result(sid, "story_outline")
        if not step or "mindmap" not in step["result_data"]:
            continue
        story = store.story_dir(sid)
        path = f"workspace/{story.name}/01-outline/outline.md" if story else ""
        flags = {k: v for k, v in step["result_data"].items() if k.startswith("_")}
        sm_script.update_step_result(sid, "story_outline", {
            **flags, "_artifact": "workspace", "path": path,
        })
        stats["outlines"] += 1

    for vsid in iter_video_sessions(sm_video):
        step = sm_video.get_step_result(vsid, "storyboard_outline")
        if not step or "segments" not in step["result_data"]:
            continue
        selected = sm_video.get_step_result(vsid, "select_episode")["result_data"]
        story = store.story_dir(selected.get("script_session_id", ""))
        vs_dir = store.storyboard_dir(
            selected.get("script_session_id", ""), selected.get("episode_id", ""), vsid,
        )
        path = f"workspace/{story.name}/{vs_dir.relative_to(story).as_posix()}/storyboard.md" if story else ""
        flags = {k: v for k, v in step["result_data"].items() if k.startswith("_")}
        sm_video.update_step_result(vsid, "storyboard_outline", {
            **flags, "_artifact": "workspace", "path": path,
        })
        stats["storyboards"] += 1

    # 4. 影子表数据清理（可选；表结构永不 DROP，备份可回滚）
    if purge_tables:
        import sqlite3
        with sqlite3.connect("data/sessions.db") as conn:
            stats["episodes"] = conn.execute("DELETE FROM episodes").rowcount
            stats["entities"] = conn.execute("DELETE FROM script_entities").rowcount
            conn.commit()

    print(f"cutover 完成: {stats}")
    print("（此后 --export/--verify 停用：文件已是唯一权威源，DB 内容行不再回流）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DB → workspace 文件迁移")
    parser.add_argument("--export", action="store_true", help="导出 DB 数据为工作区文件（幂等；cutover 后停用）")
    parser.add_argument("--verify", action="store_true", help="DB ↔ 文件对账（差异非零退出；cutover 后停用）")
    parser.add_argument("--cutover", action="store_true", help="DB 瘦身：备份后把内容行换薄 envelope")
    parser.add_argument("--purge-tables", action="store_true", help="cutover 时顺带清空 episodes/script_entities 影子数据（永不 DROP 表）")
    args = parser.parse_args()

    sm_video, sm_script, _, _ = build_managers()

    if args.export:
        if not _has_content_rows(sm_video, sm_script):
            print("已 cutover：DB 无未迁移内容行，--export 停用（文件为唯一权威源）")
            return 1
        return do_export()
    if args.verify:
        if not _has_content_rows(sm_video, sm_script):
            print("已 cutover：DB 无未迁移内容行，--verify 停用（文件为唯一权威源）")
            return 1
        return do_verify()
    if args.cutover:
        return do_cutover(args.purge_tables)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
