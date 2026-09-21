"""剧本创作工作流 API（/api/v1/script-sessions）

4 步：story_ideation → story_outline → episode_design → lookbook_images
- 形态 A（第 1 步对话/finalize）：SSE 请求内直跑，断开即取消
- 形态 B（第 2/3/4 步生成）：POST 立即返回 run_id，前端连 /agent-runs/{run_id}/events 观流

业务异常（ScriptWorkflowError）由 main.py 的全局异常 handler 统一转 HTTP detail。
"""
import asyncio
import logging
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path

from backend.core.agent_sdk import sse_direct_response
from backend.core.persistence.workspace_store import ENTITY_ID_PATTERN, EPISODE_ID_PATTERN
from backend.core.services.lookbook_library_service import (
    import_lookbook_from_library,
    list_lookbook_library,
)
from backend.core.services.step_payload import script_step_results, script_title
from backend.deps import (
    get_model_manager,
    get_script_manager,
    get_script_session_manager,
    get_script_workflow,
    get_workspace_store,
    load_script_session,
    run_agent_endpoint,
)
from backend.schemas.script import (
    CreateScriptSessionRequest,
    EntityUpsertRequest,
    EpisodeRegenerateRequest,
    EpisodeUpdateRequest,
    EpisodesGenerateRequest,
    IdeationAdoptRequest,
    IdeationMessageRequest,
    IdeationTitleRequest,
    LookbookGenerateRequest,
    LookbookImportRequest,
    LookbookRegenerateRequest,
    OutlineGenerateRequest,
    OutlineUpdateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 路径参数 ID 白名单（与 store 层/schema 共用同一 pattern，防多处定义漂移；
# 这里 422 快速失败防 glob 元字符注入）
EPISODE_ID_PATH = Path(pattern=EPISODE_ID_PATTERN)
ENTITY_ID_PATH = Path(pattern=ENTITY_ID_PATTERN)


# ==================== 会话 CRUD ====================

@router.post("", status_code=201)
async def create_script_session(body: CreateScriptSessionRequest):
    sm = get_script_session_manager()
    session_id = str(uuid.uuid4())
    info = sm.create_session(session_id, workflow_type="script")
    # 即刻建工作区 story 树（未命名剧本，大纲生成时随剧名正名）
    get_workspace_store().ensure_story(session_id)
    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "created_at": info["created_at"],
            "updated_at": info["updated_at"],
            "current_step": info["current_step"],
            "status": info["status"],
            "completed_steps": [],
            "step_results": {},
        },
    }


@router.get("")
async def list_script_sessions():
    sm = get_script_session_manager()
    store = get_workspace_store()
    sessions = []
    for info in sm.list_sessions(workflow_type="script"):
        sessions.append({
            "session_id": info["session_id"],
            "title": script_title(store, info["session_id"]),
            "created_at": info["created_at"],
            "updated_at": info["updated_at"],
            "current_step": info.get("current_step") or sm.STEPS[0],
            "status": info.get("status") or "active",
            "completed_steps": sm.get_completed_steps(info["session_id"]),
        })
    return {"success": True, "data": {"sessions": sessions, "total": len(sessions)}}


@router.get("/{session_id}")
async def get_script_session(session_id: str, info: dict = Depends(load_script_session)):
    sm = get_script_session_manager()
    return {
        "success": True,
        "data": {
            "session_id": info["session_id"],
            "created_at": info["created_at"],
            "updated_at": info["updated_at"],
            "current_step": info.get("current_step") or sm.STEPS[0],
            "status": info.get("status") or "active",
            "workflow_type": info.get("workflow_type"),
            "completed_steps": sm.get_completed_steps(session_id),
            "step_results": script_step_results(sm, get_workspace_store(), session_id),
        },
    }


@router.delete("/{session_id}")
async def delete_script_session(session_id: str, _info: dict = Depends(load_script_session)):
    get_script_session_manager().delete_session(session_id)
    get_script_manager().delete_script_data(session_id)
    get_workspace_store().delete_story(session_id)
    return {"success": True, "message": f"剧本会话 {session_id} 已删除"}


# ==================== SSE 形态 A：请求内直跑 ====================
# 编排在 core/agent_sdk/direct.py（sse_direct_response），router 只留 HTTP 包装


@router.post("/{session_id}/ideation/message")
async def ideation_message(session_id: str, body: IdeationMessageRequest, _info: dict = Depends(load_script_session)):
    """用户消息（SSE 直跑）"""
    workflow = get_script_workflow()

    def factory(on_event, interrupt):
        return workflow.ideation_message(session_id, body.message, on_event, interrupt)

    return sse_direct_response(factory)


@router.post("/{session_id}/ideation/finalize")
async def ideation_finalize(session_id: str, _info: dict = Depends(load_script_session)):
    """收敛故事逻辑（SSE 直跑，推进步骤）"""
    workflow = get_script_workflow()

    def factory(on_event, interrupt):
        return workflow.ideation_finalize(session_id, on_event, interrupt)

    return sse_direct_response(factory)


@router.get("/{session_id}/ideation")
async def get_ideation(session_id: str, _info: dict = Depends(load_script_session)):
    """构思历史（messages + story_logic）"""
    data = get_script_workflow().get_ideation(session_id)
    return {"success": True, "data": data}


@router.put("/{session_id}/ideation")
async def update_ideation_story_logic(session_id: str, body: dict, _info: dict = Depends(load_script_session)):
    """人工编辑故事逻辑（不推进不重置）"""
    story_logic = (body or {}).get("story_logic", "")
    if not story_logic.strip():
        raise HTTPException(status_code=400, detail="story_logic 不能为空")
    result = get_script_workflow().update_story_logic(session_id, story_logic)
    return {"success": True, "data": result}


@router.put("/{session_id}/ideation/title")
async def set_ideation_story_title(session_id: str, body: IdeationTitleRequest, _info: dict = Depends(load_script_session)):
    """手动设定剧名（manual 锁定，AI 收敛不再覆盖；置空解除锁定）"""
    result = get_script_workflow().set_story_title(session_id, body.title)
    return {"success": True, "data": result}


@router.post("/{session_id}/ideation/adopt")
async def adopt_ideation_story_logic(session_id: str, body: IdeationAdoptRequest, _info: dict = Depends(load_script_session)):
    """采纳文本为故事逻辑并完成第 1 步（不经 LLM 收敛）"""
    result = get_script_workflow().adopt_story_logic(session_id, body.story_logic)
    return {"success": True, "data": result}


# ==================== 第 2 步：故事大纲 ====================

@router.post("/{session_id}/outline/generate")
async def generate_outline(session_id: str, body: OutlineGenerateRequest, _info: dict = Depends(load_script_session)):
    """生成故事大纲 → {run_id}（重生成会级联清下游，由 workflow 内部处理）"""
    sm = get_script_session_manager()
    if not sm.is_step_completed(session_id, "story_ideation"):
        raise HTTPException(status_code=400, detail="请先完成故事构思（第 1 步）")
    workflow = get_script_workflow()

    def factory(on_event, interrupt):
        return workflow.generate_outline(session_id, body.model_dump(), on_event, interrupt)

    return run_agent_endpoint("story_outline", factory)


@router.get("/{session_id}/outline")
async def get_outline(session_id: str, _info: dict = Depends(load_script_session)):
    outline = get_workspace_store().read_outline(session_id) or {}
    return {"success": True, "data": outline}


@router.put("/{session_id}/outline")
async def update_outline(session_id: str, body: OutlineUpdateRequest, _info: dict = Depends(load_script_session)):
    """人工编辑大纲（不推进不重置）"""
    result = get_script_workflow().update_outline(session_id, body.mindmap)
    return {"success": True, "data": result}


# ==================== 第 3 步：分集设计 ====================

@router.post("/{session_id}/episodes/generate")
async def generate_episodes(session_id: str, body: EpisodesGenerateRequest, _info: dict = Depends(load_script_session)):
    """全量分集设计 → {run_id}（agent 工具增量落库，前端轮询 GET episodes）"""
    sm = get_script_session_manager()
    if not sm.is_step_completed(session_id, "story_outline"):
        raise HTTPException(status_code=400, detail="请先生成故事大纲（第 2 步）")
    workflow = get_script_workflow()

    def factory(on_event, interrupt):
        return workflow.generate_episodes(
            session_id, on_event, interrupt,
            extra_instruction=body.extra_instruction,
        )

    return run_agent_endpoint("episode_design", factory)


@router.post("/{session_id}/episodes/regenerate")
async def regenerate_episode(session_id: str, body: EpisodeRegenerateRequest, _info: dict = Depends(load_script_session)):
    """单集重设计 → {run_id}（episode_id 不变，不破坏下游引用）"""
    sm = get_script_session_manager()
    if not sm.is_step_completed(session_id, "episode_design"):
        raise HTTPException(status_code=400, detail="请先完成分集设计（第 3 步）")
    workflow = get_script_workflow()

    def factory(on_event, interrupt):
        return workflow.generate_episodes(
            session_id, on_event, interrupt,
            regenerate_episode_id=body.episode_id,
            extra_instruction=body.extra_instruction,
        )

    return run_agent_endpoint(f"episode_redesign_{body.episode_id}", factory)


@router.get("/{session_id}/episodes")
async def list_episodes(session_id: str, _info: dict = Depends(load_script_session)):
    """分集列表（生成期间前端 2s 轮询，时间线逐集点亮）"""
    episodes = get_workspace_store().list_episodes(session_id)
    return {"success": True, "data": {"episodes": episodes, "total": len(episodes)}}


@router.get("/{session_id}/episodes/{episode_id}")
async def get_episode(session_id: str, episode_id: Annotated[str, EPISODE_ID_PATH], _info: dict = Depends(load_script_session)):
    episode = get_workspace_store().get_episode(session_id, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail=f"分集不存在: {episode_id}")
    return {"success": True, "data": episode}


@router.put("/{session_id}/episodes/{episode_id}")
async def update_episode(session_id: str, episode_id: Annotated[str, EPISODE_ID_PATH], body: EpisodeUpdateRequest, _info: dict = Depends(load_script_session)):
    """人工编辑分集（部分字段；refs 类字段走与 save_episode 相同的引用校验）"""
    updated = get_script_workflow().update_episode_fields(
        session_id, episode_id, body.model_dump(exclude_none=True),
    )
    return {"success": True, "data": updated}


@router.delete("/{session_id}/episodes/{episode_id}")
async def delete_episode(session_id: str, episode_id: Annotated[str, EPISODE_ID_PATH], _info: dict = Depends(load_script_session)):
    """删除分集（仅允许删除最后一集，保持集号连续）"""
    try:
        ok = get_workspace_store().delete_last_episode(session_id, episode_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"分集不存在: {episode_id}")
    return {"success": True, "message": f"{episode_id} 已删除"}


# ==================== 实体库 ====================

@router.get("/{session_id}/entities")
async def list_entities(session_id: str, entity_type: Optional[str] = None, _info: dict = Depends(load_script_session)):
    entities = get_workspace_store().list_entities(session_id, entity_type)
    return {"success": True, "data": {"entities": entities, "total": len(entities)}}


def _upsert_entity(session_id: str, body: EntityUpsertRequest, entity_id: Optional[str] = None) -> dict:
    """人工新增/更新实体：指定 entity_id 时先校验存在（404），ValueError 统一转 400"""
    store = get_workspace_store()
    if entity_id and not store.get_entity(session_id, entity_id):
        raise HTTPException(status_code=404, detail=f"实体不存在或不属于该会话: {entity_id}")
    try:
        return store.upsert_entity(
            session_id, body.entity_type, body.name, body.description, body.meta,
            entity_id=entity_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{session_id}/entities")
async def upsert_entity(session_id: str, body: EntityUpsertRequest, _info: dict = Depends(load_script_session)):
    """人工新增/更新实体（ID 由后端分配）"""
    entity = _upsert_entity(session_id, body)
    return {"success": True, "data": entity}


@router.put("/{session_id}/entities/{entity_id}")
async def update_entity(session_id: str, entity_id: Annotated[str, ENTITY_ID_PATH], body: EntityUpsertRequest, _info: dict = Depends(load_script_session)):
    entity = _upsert_entity(session_id, body, entity_id)
    return {"success": True, "data": entity}


@router.get("/{session_id}/entities/{entity_id}/references")
async def get_entity_references(session_id: str, entity_id: Annotated[str, ENTITY_ID_PATH], _info: dict = Depends(load_script_session)):
    """引用反查：该实体在全部分集中的引用方式（人物/场景 → 出场；线索/伏笔 → action 值）"""
    episodes = get_workspace_store().entity_references(session_id, entity_id)
    if episodes is None:
        raise HTTPException(status_code=404, detail=f"实体不存在或不属于该会话: {entity_id}")
    return {"success": True, "data": {"entity_id": entity_id, "episodes": episodes}}


@router.delete("/{session_id}/entities/{entity_id}")
async def delete_entity(session_id: str, entity_id: Annotated[str, ENTITY_ID_PATH], _info: dict = Depends(load_script_session)):
    """删除实体（不属于本会话或被分集反向引用时拒绝；校验+删除同锁原子完成）"""
    store = get_workspace_store()
    try:
        ok = store.delete_entity_unreferenced(session_id, entity_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail=f"实体不存在或不属于该会话: {entity_id}")
    return {"success": True, "message": f"实体 {entity_id} 已删除"}


# ==================== 第 4 步：核心素材 ====================


def _require_default_image_model(model_config_id: Optional[str]) -> None:
    """生图路由前置校验：未指定配置且无默认生图模型时直接 400（否则要连上 run 流才看到报错）"""
    if not model_config_id and not get_model_manager().get_default_model("image"):
        raise HTTPException(
            status_code=400,
            detail="未配置默认生图模型：请在「模型管理」添加模型类型为「生图」的配置并设为默认",
        )


@router.post("/{session_id}/lookbook/generate")
async def generate_lookbook(session_id: str, body: LookbookGenerateRequest, _info: dict = Depends(load_script_session)):
    """勾选实体生成核心素材 → {run_id}（agent 出 prompt + 确定性生图）"""
    _require_default_image_model(body.model_config_id)
    workflow = get_script_workflow()

    def factory(on_event, interrupt):
        return workflow.generate_lookbook(
            session_id, body.entity_ids, body.style_prompt,
            body.model_config_id, on_event, interrupt,
        )

    return run_agent_endpoint("lookbook_images", factory)


@router.post("/{session_id}/lookbook/complete")
async def complete_lookbook(session_id: str, _info: dict = Depends(load_script_session)):
    """手动确认完成第 4 步"""
    result = get_script_workflow().complete_lookbook(session_id)
    return {"success": True, "data": result}


@router.get("/{session_id}/lookbook")
async def list_lookbook(session_id: str, entity_id: Optional[str] = None, task_status: Optional[str] = None, _info: dict = Depends(load_script_session)):
    rows = get_script_manager().list_lookbook(session_id, entity_id, task_status)
    return {"success": True, "data": {"images": rows, "total": len(rows)}}


@router.get("/{session_id}/lookbook/library")
async def get_lookbook_library(session_id: str, _info: dict = Depends(load_script_session)):
    """素材库：全部存活剧本会话的已完成核心素材（含当前剧本历史素材），按会话分组"""
    # to_thread：跨全部会话的 SQLite 扫描 + 逐会话磁盘 IO，同步执行会阻塞事件循环（SSE 观流卡顿）
    data = await asyncio.to_thread(
        list_lookbook_library,
        get_script_session_manager(), get_workspace_store(), get_script_manager(), session_id,
    )
    return {"success": True, "data": data}


@router.post("/{session_id}/lookbook/import")
async def import_lookbook_image(session_id: str, body: LookbookImportRequest, _info: dict = Depends(load_script_session)):
    """从素材库复制素材到当前会话并锚定到实体（引用同一图片 URL，无额外存储）"""
    data = await asyncio.to_thread(
        import_lookbook_from_library,
        get_workspace_store(), get_script_manager(),
        session_id, body.entity_id, body.source_image_id,
    )
    return {"success": True, "data": data}


@router.post("/{session_id}/lookbook/{image_id}/regenerate")
async def regenerate_lookbook_image(session_id: str, image_id: str, body: LookbookRegenerateRequest, _info: dict = Depends(load_script_session)):
    """单张核心素材重生成 → {run_id}"""
    _require_default_image_model(body.model_config_id)
    workflow = get_script_workflow()

    def factory(on_event, interrupt):
        async def run():
            return {
                "image": await workflow.regenerate_lookbook_image(
                    session_id, image_id, body.prompt, body.model_config_id,
                )
            }
        return run()

    return run_agent_endpoint(f"lookbook_regen_{image_id}", factory)


@router.delete("/{session_id}/lookbook/{image_id}")
async def delete_lookbook_image(session_id: str, image_id: str, _info: dict = Depends(load_script_session)):
    ok = get_script_manager().delete_lookbook(session_id, image_id)
    return {"success": ok, "message": "核心素材已删除" if ok else "核心素材不存在"}
