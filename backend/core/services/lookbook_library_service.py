"""核心素材素材库：跨剧本会话/本剧本历史的已完成素材查询 + 复制导入锚定

- 查询：全局已完成核心素材按剧本会话分组（当前会话组排第一，其余按最新素材倒序）；
  仅收录存活剧本会话（script-sessions 删除为三步非事务操作，中途失败仍可能残留
  孤儿行，死会话素材不进素材库——防御性过滤）
- 导入：复制源行为当前会话新行（引用同一远程 URL，无额外存储），meta 记 imported_from 溯源，
  再回写实体 frontmatter 锚点；不做跨会话直接引用（源会话删除不受影响）；
  校验源/目标实体类型一致（meta.entity_type → 源实体文件，均无则放行历史素材）
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
    return {"groups": groups}


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
    target = store.get_entity(session_id, entity_id)
    if not target:
        raise WorkflowError(f"实体不存在或不属于该会话: {entity_id}", status_code=404)
    if target.get("entity_type") not in ("character", "scene"):
        raise WorkflowError(f"仅人物/场景实体可绑定核心素材: {target.get('entity_type')}")
    # 源实体类型校验：meta.entity_type（新行/导入复制行都有）→ 源实体文件（可能已被
    # 级联删除）→ 均无则放行（无法判定的历史素材，用户自担）
    source_type = (source.get("meta") or {}).get("entity_type") or ""
    if not source_type:
        source_entity = store.get_entity(source["script_session_id"], source["entity_id"])
        source_type = (source_entity or {}).get("entity_type") or ""
    if source_type and source_type != target["entity_type"]:
        raise WorkflowError(
            f"素材类型不匹配：{'人物' if target['entity_type'] == 'character' else '场景'}"
            f"实体不能绑定{'场景' if source_type == 'scene' else '人物'}素材"
        )

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
