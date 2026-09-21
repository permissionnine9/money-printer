"""定妆照素材库：跨剧本会话/本剧本历史的已完成素材查询 + 复制导入锚定

- 查询：全局已完成定妆照按剧本会话分组（当前会话组排第一，其余按最新素材倒序）；
  仅收录存活剧本会话（通用会话删除端点不清理 lookbook 表、script-sessions 删除
  中途失败都可能残留孤儿行，死会话素材不进素材库）
- 导入：复制源行为当前会话新行（引用同一远程 URL，无额外存储），meta 记 imported_from 溯源，
  再回写实体 frontmatter 锚点；不做跨会话直接引用（源会话删除不受影响）
"""
from backend.core.errors import WorkflowError
from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.session_manager import SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore
from backend.core.services.step_payload import script_title


def list_lookbook_library(sm: SessionManager, store: WorkspaceStore, scm: ScriptManager, session_id: str) -> dict:
    """素材库分组：当前剧本（含历史素材）排第一，其余剧本按最新素材倒序"""
    alive = {s["session_id"] for s in sm.list_sessions(workflow_type="script")}
    by_session: dict[str, list[dict]] = {}
    for row in scm.list_completed_lookbooks():
        if row["script_session_id"] in alive:
            by_session.setdefault(row["script_session_id"], []).append(row)

    def _session_label(sid: str) -> str:
        return script_title(store, sid) or f"剧本 {sid[:8]}"

    def _group(sid: str, rows: list[dict]) -> dict:
        entity_names = {e["entity_id"]: e.get("name", "") for e in store.list_entities(sid)}
        return {
            "key": "current" if sid == session_id else sid,
            "session_id": sid,
            "is_current": sid == session_id,
            "label": f"当前剧本《{_session_label(sid)}》" if sid == session_id else f"《{_session_label(sid)}》",
            "materials": [
                {
                    "image_id": row["image_id"],
                    "image_path": row["image_path"],
                    "description": row.get("description", ""),
                    "entity_id": row["entity_id"],
                    "entity_name": entity_names.get(row["entity_id"], ""),
                    "entity_exists": row["entity_id"] in entity_names,
                    "created_at": row.get("created_at", ""),
                }
                for row in rows
            ],
        }

    others = sorted(
        ((sid, rows) for sid, rows in by_session.items() if sid != session_id),
        key=lambda item: item[1][0]["created_at"],  # rows 为 created_at DESC，取组内最新
        reverse=True,
    )
    groups = []
    if session_id in by_session:
        groups.append(_group(session_id, by_session[session_id]))
    groups.extend(_group(sid, rows) for sid, rows in others)
    return {"groups": groups, "total": sum(len(g["materials"]) for g in groups)}


def import_lookbook_from_library(
    store: WorkspaceStore,
    scm: ScriptManager,
    session_id: str,
    entity_id: str,
    source_image_id: str,
) -> dict:
    """复制素材库源行为当前会话新行并锚定到实体，返回 {image, entity}"""
    source = scm.get_lookbook(source_image_id)
    if not source:
        raise WorkflowError(f"素材不存在: {source_image_id}", status_code=404)
    if source.get("task_status") != "completed" or not source.get("image_path"):
        raise WorkflowError(f"素材尚未生成完成: {source_image_id}")
    if not store.get_entity(session_id, entity_id):
        raise WorkflowError(f"实体不存在或不属于该会话: {entity_id}", status_code=404)

    row = scm.insert_lookbook(
        session_id, entity_id,
        prompt=source.get("prompt", ""),
        description=source.get("description", ""),
        task_status="completed",
        image_path=source["image_path"],
        meta={
            **(source.get("meta") or {}),
            "imported_from": {
                "image_id": source_image_id,
                "script_session_id": source["script_session_id"],
                "entity_id": source["entity_id"],
            },
        },
    )
    try:
        anchored = store.set_entity_lookbook(session_id, entity_id, row["image_id"], row["image_path"])
    except Exception:
        scm.delete_lookbook(session_id, row["image_id"])  # 实体文件写入异常（磁盘满/只读等），回滚复制行
        raise
    if not anchored:
        scm.delete_lookbook(session_id, row["image_id"])  # 实体在校验后被并发删除，回滚复制行
        raise WorkflowError(f"实体不存在或不属于该会话: {entity_id}", status_code=404)
    return {"image": row, "entity": store.get_entity(session_id, entity_id)}
