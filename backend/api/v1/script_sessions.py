"""剧本创作工作流 API（/api/v1/script-sessions）

4 步：story_ideation → story_outline → episode_design → lookbook_images
- 形态 A（第 1 步对话/finalize）：SSE 请求内直跑，断开即取消
- 形态 B（第 2/3/4 步生成）：POST 立即返回 run_id，前端连 /agent-runs/{run_id}/events 观流

业务异常（ScriptWorkflowError）由 main.py 的全局异常 handler 统一转 HTTP detail。
"""
import asyncio
import json
import logging
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import StreamingResponse

from backend.core.agent_sdk import AgentEvent
from backend.core.agents.script_workflow import ScriptWorkflow
from backend.core.persistence.workspace_store import ENTITY_ID_PATTERN, EPISODE_ID_PATTERN
from backend.core.services.workspace_projection import script_step_results, script_title
from backend.deps import (
    get_model_manager,
    get_script_manager,
    get_script_session_manager,
    get_workspace_store,
    load_script_session,
    start_agent_run,
)
from backend.schemas.script import (
    CreateScriptSessionRequest,
    EntityUpsertRequest,
    EpisodeRegenerateRequest,
    EpisodeUpdateRequest,
    EpisodesGenerateRequest,
    IdeationMessageRequest,
    LookbookGenerateRequest,
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


def get_script_workflow() -> ScriptWorkflow:
    return ScriptWorkflow(
        session_manager=get_script_session_manager(),
        script_manager=get_script_manager(),
        store=get_workspace_store(),
    )


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
            "title": script_title(sm, store, info["session_id"]),
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

def _sse_direct(coro_factory):
    """形态 A：SSE 响应内直接跑 agent，事件经队列转流；断开触发 interrupt 后取消"""
    interrupt_holder: dict = {}

    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        FINAL = object()

        async def runner():
            interrupt = asyncio.Event()
            interrupt_holder["event"] = interrupt

            def on_event(ev: AgentEvent) -> None:
                queue.put_nowait(ev)

            try:
                data = await coro_factory(on_event, interrupt)
                await queue.put(("final", data))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("[剧本SSE] agent 运行异常")
                await queue.put(("final_err", str(e)))
            finally:
                await queue.put(FINAL)

        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is FINAL:
                    break
                if isinstance(item, AgentEvent):
                    yield item.to_sse(0)
                else:
                    kind, payload = item
                    if kind == "final":
                        yield f"data: {json.dumps({'type': 'final', 'data': payload}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'error', 'message': payload}, ensure_ascii=False)}\n\n"
        finally:
            # 客户端断开：先 interrupt（优雅终止），5 秒宽限后强取消
            event = interrupt_holder.get("event")
            if event and not task.done():
                event.set()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    task.cancel()
            elif not task.done():
                task.cancel()
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ==================== 第 1 步：故事构思 ====================

@router.post("/{session_id}/ideation/message")
async def ideation_message(session_id: str, body: IdeationMessageRequest, _info: dict = Depends(load_script_session)):
    """用户消息（SSE 直跑）"""
    workflow = get_script_workflow()

    def factory(on_event, interrupt):
        return workflow.ideation_message(session_id, body.message, on_event, interrupt)

    return _sse_direct(factory)


@router.post("/{session_id}/ideation/finalize")
async def ideation_finalize(session_id: str, _info: dict = Depends(load_script_session)):
    """收敛故事逻辑（SSE 直跑，推进步骤）"""
    workflow = get_script_workflow()

    def factory(on_event, interrupt):
        return workflow.ideation_finalize(session_id, on_event, interrupt)

    return _sse_direct(factory)


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

    return start_agent_run("story_outline", factory)


@router.get("/{session_id}/outline")
async def get_outline(session_id: str, _info: dict = Depends(load_script_session)):
    projected = script_step_results(
        get_script_session_manager(), get_workspace_store(), session_id,
    ).get("story_outline")
    return {"success": True, "data": (projected or {}).get("result_data") or {}}


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

    return start_agent_run("episode_design", factory)


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

    return start_agent_run(f"episode_redesign_{body.episode_id}", factory)


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
    store = get_workspace_store()
    episodes = store.list_episodes(session_id)
    if not episodes or episodes[-1]["episode_id"] != episode_id:
        raise HTTPException(status_code=400, detail="只能删除最后一集（保持集号连续）")
    store.delete_episode(session_id, episode_id)
    return {"success": True, "message": f"{episode_id} 已删除"}


# ==================== 实体库 ====================

@router.get("/{session_id}/entities")
async def list_entities(session_id: str, entity_type: Optional[str] = None, _info: dict = Depends(load_script_session)):
    entities = get_workspace_store().list_entities(session_id, entity_type)
    return {"success": True, "data": {"entities": entities, "total": len(entities)}}


@router.post("/{session_id}/entities")
async def upsert_entity(session_id: str, body: EntityUpsertRequest, _info: dict = Depends(load_script_session)):
    """人工新增/更新实体（ID 由后端分配）"""
    try:
        entity = get_workspace_store().upsert_entity(
            session_id, body.entity_type, body.name, body.description, body.meta,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "data": entity}


@router.put("/{session_id}/entities/{entity_id}")
async def update_entity(session_id: str, entity_id: Annotated[str, ENTITY_ID_PATH], body: EntityUpsertRequest, _info: dict = Depends(load_script_session)):
    store = get_workspace_store()
    if not store.get_entity(session_id, entity_id):
        raise HTTPException(status_code=404, detail=f"实体不存在或不属于该会话: {entity_id}")
    try:
        entity = store.upsert_entity(
            session_id, body.entity_type, body.name, body.description, body.meta,
            entity_id=entity_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "data": entity}


@router.get("/{session_id}/entities/{entity_id}/references")
async def get_entity_references(session_id: str, entity_id: Annotated[str, ENTITY_ID_PATH], _info: dict = Depends(load_script_session)):
    """引用反查：该实体在全部分集中的引用方式（人物/场景 → 出场；线索/伏笔 → action 值）"""
    store = get_workspace_store()
    entity = store.get_entity(session_id, entity_id)
    if not entity or entity["script_session_id"] != session_id:
        raise HTTPException(status_code=404, detail=f"实体不存在或不属于该会话: {entity_id}")
    entity_type = entity["entity_type"]
    episodes = []
    for ep in store.list_episodes(session_id):
        if entity_type == "character":
            actions = ["出场"] if entity_id in ep["character_ids"] else []
        elif entity_type == "scene":
            actions = ["出场"] if entity_id in ep["scene_ids"] else []
        else:
            refs = ep["clue_refs"] if entity_type == "clue" else ep["foreshadow_refs"]
            actions = [r.get("action", "") for r in refs if r.get("entity_id") == entity_id]
        if actions:
            episodes.append({"episode_id": ep["episode_id"], "title": ep["title"], "actions": actions})
    return {"success": True, "data": {"entity_id": entity_id, "episodes": episodes}}


@router.delete("/{session_id}/entities/{entity_id}")
async def delete_entity(session_id: str, entity_id: Annotated[str, ENTITY_ID_PATH], _info: dict = Depends(load_script_session)):
    """删除实体（不属于本会话或被分集反向引用时拒绝）"""
    store = get_workspace_store()
    if not store.get_entity(session_id, entity_id):
        raise HTTPException(status_code=404, detail=f"实体不存在或不属于该会话: {entity_id}")
    for episode in store.list_episodes(session_id):
        referenced = (
            episode["character_ids"] + episode["scene_ids"]
            + [r.get("entity_id") for r in episode["clue_refs"]]
            + [r.get("entity_id") for r in episode["foreshadow_refs"]]
        )
        if entity_id in referenced:
            raise HTTPException(
                status_code=400,
                detail=f"实体 {entity_id} 被分集 {episode['episode_id']} 引用，先移除引用再删除",
            )
    ok = store.delete_entity(session_id, entity_id)
    return {"success": ok, "message": f"实体 {entity_id} 已删除" if ok else "实体不存在"}


# ==================== 第 4 步：定妆照 ====================


def _require_default_image_model(model_config_id: Optional[str]) -> None:
    """生图路由前置校验：未指定配置且无默认生图模型时直接 400（否则要连上 run 流才看到报错）"""
    if not model_config_id and not get_model_manager().get_default_model("image"):
        raise HTTPException(
            status_code=400,
            detail="未配置默认生图模型：请在「模型管理」添加模型类型为「生图」的配置并设为默认",
        )


@router.post("/{session_id}/lookbook/generate")
async def generate_lookbook(session_id: str, body: LookbookGenerateRequest, _info: dict = Depends(load_script_session)):
    """勾选实体生成定妆照 → {run_id}（agent 出 prompt + 确定性生图）"""
    _require_default_image_model(body.model_config_id)
    workflow = get_script_workflow()

    def factory(on_event, interrupt):
        return workflow.generate_lookbook(
            session_id, body.entity_ids, body.style_prompt,
            body.model_config_id, on_event, interrupt,
        )

    return start_agent_run("lookbook_images", factory)


@router.post("/{session_id}/lookbook/complete")
async def complete_lookbook(session_id: str, _info: dict = Depends(load_script_session)):
    """手动确认完成第 4 步"""
    result = get_script_workflow().complete_lookbook(session_id)
    return {"success": True, "data": result}


@router.get("/{session_id}/lookbook")
async def list_lookbook(session_id: str, entity_id: Optional[str] = None, task_status: Optional[str] = None, _info: dict = Depends(load_script_session)):
    rows = get_script_manager().list_lookbook(session_id, entity_id, task_status)
    return {"success": True, "data": {"images": rows, "total": len(rows)}}


@router.post("/{session_id}/lookbook/{image_id}/regenerate")
async def regenerate_lookbook_image(session_id: str, image_id: str, body: LookbookRegenerateRequest, _info: dict = Depends(load_script_session)):
    """单张定妆照重生成 → {run_id}"""
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

    return start_agent_run(f"lookbook_regen_{image_id}", factory)


@router.delete("/{session_id}/lookbook/{image_id}")
async def delete_lookbook_image(session_id: str, image_id: str, _info: dict = Depends(load_script_session)):
    ok = get_script_manager().delete_lookbook(session_id, image_id)
    return {"success": ok, "message": "定妆照已删除" if ok else "定妆照不存在"}
