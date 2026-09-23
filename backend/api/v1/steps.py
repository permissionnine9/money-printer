"""
工作流步骤 API（视频工作流 4 步）

1. select_episode      从剧本选集
2. storyboard_outline  分镜大纲（生成/编辑，AgentRunRegistry 观流）
3. segment_management  分镜管理（分镜配置 / 提示词生成 / 完成标记）
4. generate_videos     视频生成（后台任务 + 轮询）

业务异常（StoryboardError）由 main.py 的全局异常 handler 统一转 HTTP detail。
"""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from backend.schemas.steps import (
    SelectEpisodeRequest,
    StoryboardOutlineGenerateRequest,
    StoryboardOutlineUpdateRequest,
    SegmentConfigUpdateRequest,
    SegmentPromptUpdateRequest,
    SegmentReferenceImagesUpdateRequest,
    SegmentMaterialGenerateRequest,
    SegmentCompleteRequest,
    GenerateVideosRequest,
    StepResponse,
)
from backend.deps import (
    get_session_manager,
    get_storyboard_workflow,
    get_workflow,
    load_video_session,
    run_agent_endpoint,
)
from backend.core.persistence.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{session_id}/select-episode", response_model=StepResponse)
async def step_1_select_episode(
    session_id: str,
    request: SelectEpisodeRequest,
    session_manager: SessionManager = Depends(get_session_manager),
    _session_info: dict = Depends(load_video_session),
):
    """步骤1：从剧本选集（绑定分集设计与视频参数）"""
    logger.info(f"[API] 步骤1 - 从剧本选集 - 会话: {session_id[:8]}... 分集: {request.episode_id}")

    video_params = {
        "resolution": request.resolution,
        "aspect_ratio": request.aspect_ratio,
        "film_style": request.film_style,
        "max_segment_duration": request.max_segment_duration,
    }
    result = get_workflow().step_select_episode(
        session_id, request.script_session_id, request.episode_id, video_params,
    )

    result_data = session_manager.get_step_result(session_id, "select_episode")
    return StepResponse(
        success=True,
        message=result.get("message", "已选择分集"),
        data=result_data,
    )


# ==================== 步骤 2：分镜大纲 ====================

@router.post("/{session_id}/storyboard-outline/generate")
async def generate_storyboard_outline(
    session_id: str,
    body: StoryboardOutlineGenerateRequest | None = None,
    session_manager: SessionManager = Depends(get_session_manager),
    _session_info: dict = Depends(load_video_session),
):
    """步骤2：生成分镜大纲 → {run_id}（重生成会级联清空分镜配置与提示词）"""
    can_execute, reason = session_manager.can_execute_step(session_id, "storyboard_outline")
    if not can_execute:
        raise HTTPException(status_code=400, detail=reason or "请先完成步骤1：从剧本选集")

    workflow = get_storyboard_workflow()
    extra_prompt = (body.extra_prompt if body else "") or ""

    def factory(on_event, interrupt):
        return workflow.generate_outline(session_id, extra_prompt, on_event, interrupt)

    return run_agent_endpoint("storyboard_outline", factory)


@router.put("/{session_id}/storyboard-outline")
async def update_storyboard_outline(
    session_id: str,
    body: StoryboardOutlineUpdateRequest,
    _session_info: dict = Depends(load_video_session),
):
    """步骤2：保存人工编辑的导图（markdown 含 `- 分镜内容` 行，解析后同步 mindmap 与分镜列表）"""
    # to_thread：锁内整段文件读写 + SQLite 同步执行会阻塞事件循环（Agent 运行期其他请求排队）
    result = await asyncio.to_thread(
        get_storyboard_workflow().update_outline, session_id, body.mindmap,
    )
    return {"success": True, "data": result}


# ==================== 步骤 3：分镜管理 ====================

@router.put("/{session_id}/storyboard-segments/{index}/config")
async def update_segment_config(
    session_id: str,
    index: int,
    body: SegmentConfigUpdateRequest,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：更新分镜配置（分镜形式 / overlap；变化会清空该分镜已生成的提示词）"""
    result = await asyncio.to_thread(
        get_storyboard_workflow().update_segment_config,
        session_id, index, body.model_dump(exclude_none=True),
    )
    return {"success": True, "data": result}


@router.put("/{session_id}/storyboard-segments/{index}/prompt")
async def update_segment_prompt(
    session_id: str,
    index: int,
    body: SegmentPromptUpdateRequest,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：手动编辑保存分镜提示词（不清参考图、不动 configured 完成态）"""
    result = await asyncio.to_thread(
        get_storyboard_workflow().update_segment_prompt, session_id, index, body.prompt,
    )
    return {"success": True, "data": result}


@router.get("/{session_id}/material-pool")
async def get_material_pool(
    session_id: str,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：素材池（选择弹窗分组数据：核心素材 / 本集素材 / 其他集素材，不跨 story）"""
    result = await asyncio.to_thread(get_storyboard_workflow().list_material_pool, session_id)
    return {"success": True, "data": result}


@router.delete("/{session_id}/materials/{image_id}")
async def delete_material_image(
    session_id: str,
    image_id: str,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：删除分集素材图（素材池记录 + 磁盘归档文件；不清理分镜文件中的引用）"""
    selected = get_workflow().get_selected_episode(session_id)
    await asyncio.to_thread(
        get_storyboard_workflow().delete_material, selected["script_session_id"], image_id,
    )
    return {"success": True, "data": {"deleted": True, "image_id": image_id}}


@router.put("/{session_id}/storyboard-segments/{index}/reference-images")
async def update_segment_reference_images(
    session_id: str,
    index: int,
    body: SegmentReferenceImagesUpdateRequest,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：保存分镜参考素材图（全量覆盖；换图会清空该分镜已生成的提示词）"""
    result = await asyncio.to_thread(
        get_storyboard_workflow().update_segment_reference_images,
        session_id, index, [item.model_dump() for item in body.reference_images],
    )
    return {"success": True, "data": result}


@router.post("/{session_id}/storyboard-segments/{index}/generate-material")
async def generate_segment_material(
    session_id: str,
    index: int,
    body: SegmentMaterialGenerateRequest | None = None,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：AI 生成分镜素材图 → {run_id}

    LLM 需求理解（剧本/本集/分镜上下文 + @素材 + 上传参考图 + 自定义提示词）
    → 生图 → 归档 static/images/{story}/{episode}/ → 登记素材池 → 自动关联当前分镜
    """
    workflow = get_storyboard_workflow()
    payload = body or SegmentMaterialGenerateRequest()

    # fail fast：校验失败直接 400（不进 agent run）
    await asyncio.to_thread(
        workflow.validate_segment_material_request,
        session_id, index, payload.user_prompt, payload.mentioned_image_ids, payload.reference_paths,
    )

    def factory(on_event, interrupt):
        return workflow.generate_segment_material(
            session_id, index,
            user_prompt=payload.user_prompt,
            mentioned_image_ids=payload.mentioned_image_ids,
            reference_paths=payload.reference_paths,
            model_config_id=payload.model_config_id,
            on_event=on_event,
            interrupt=interrupt,
        )

    return run_agent_endpoint(f"segment_material_{index}", factory)


@router.get("/{session_id}/storyboard-segments/{index}/prompt-context")
async def get_segment_prompt_context(
    session_id: str,
    index: int,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：分镜提示词生成弹窗的上下文预览（剧本大纲/本集脚本/分镜大纲/overlap 信息）"""
    result = await asyncio.to_thread(get_storyboard_workflow().build_prompt_context, session_id, index)
    return {"success": True, "data": result}


@router.post("/{session_id}/storyboard-segments/{index}/generate-prompt")
async def generate_segment_prompt(
    session_id: str,
    index: int,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：用 video-prompt skill 生成分镜提示词 → {run_id}（仅全能参考模式）

    提示词生成后，若分镜进入 run 时无参考图，同一 run 内自动从素材池
    （核心素材 + 本集素材）匹配参考图写入；匹配失败不影响已生成的提示词。
    """
    workflow = get_storyboard_workflow()

    def factory(on_event, interrupt):
        return workflow.generate_segment_prompt(session_id, index, on_event, interrupt)

    return run_agent_endpoint(f"segment_prompt_{index}", factory)


@router.post("/{session_id}/storyboard-segments/{index}/complete", response_model=StepResponse)
async def complete_segment(
    session_id: str,
    index: int,
    body: SegmentCompleteRequest | None = None,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：完成/取消完成单个分镜的配置（≥1 个分镜完成即可进入步骤4）"""
    completed = body.completed if body else True
    result = await asyncio.to_thread(
        get_storyboard_workflow().complete_segment, session_id, index, completed,
    )
    message = "分镜配置已完成" if completed else "分镜配置已取消完成"
    return StepResponse(success=True, message=message, data=result)


# ==================== 步骤 4：生成视频 ====================

@router.post("/{session_id}/videos", response_model=StepResponse)
async def step_4_generate_videos(
    session_id: str,
    background_tasks: BackgroundTasks,
    body: GenerateVideosRequest | None = None,
    _session_info: dict = Depends(load_video_session),
):
    """步骤4：生成视频（勾选分镜子集拼接 timeline；后台任务 + 前端轮询）"""
    logger.info(f"[API] 步骤4 - 生成视频 - 会话: {session_id[:8]}...")

    workflow = get_workflow()
    segment_indexes = body.segment_indexes if body else None
    initial_data = workflow.mark_videos_generating(session_id, segment_indexes=segment_indexes)
    logger.info(f"[API] 已保存生成中状态，开始后台生成视频 - 会话: {session_id[:8]}...")

    background_tasks.add_task(workflow.run_generate_videos_sync, session_id)
    logger.info(f"[API] 视频生成任务已提交到后台队列 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message="视频生成任务已启动，正在生成中...",
        data=initial_data,
    )


@router.post("/{session_id}/comfyui/import", response_model=StepResponse)
async def step_4_comfyui_import(
    session_id: str,
    body: GenerateVideosRequest | None = None,
    _session_info: dict = Depends(load_video_session),
):
    """步骤4两段式-阶段一：导入到 ComfyUI（上传素材+构造 timeline+注入工作流并暂存，不执行）"""
    logger.info(f"[API] 步骤4 - 导入到 ComfyUI - 会话: {session_id[:8]}...")

    segment_indexes = body.segment_indexes if body else None
    global_prompt = body.global_prompt if body else ""
    workflow_name = body.workflow_name if body else None
    summary = await get_workflow().prepare_comfyui_import(
        session_id, segment_indexes, global_prompt, workflow_name,
    )

    return StepResponse(
        success=True,
        message=f"已导入到 ComfyUI：{summary['segment_count']} 段 / {summary['image_count']} 图 / 约 {summary['total_duration']}s",
        data=summary,
    )


@router.post("/{session_id}/comfyui/start", response_model=StepResponse)
async def step_4_comfyui_start(
    session_id: str,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
    _session_info: dict = Depends(load_video_session),
):
    """步骤4两段式-阶段二：开始生成（执行已导入的工作流；后台任务 + 前端轮询）"""
    logger.info(f"[API] 步骤4 - 开始生成（已导入工作流）- 会话: {session_id[:8]}...")

    import_result = session_manager.get_step_result(session_id, "comfyui_import")
    if not import_result or not (import_result.get("result_data") or {}).get("timeline_data"):
        raise HTTPException(status_code=400, detail="尚未导入到 ComfyUI，请先点击「导入到 ComfyUI」")
    segment_indexes = import_result["result_data"]["segment_indexes"]

    workflow = get_workflow()
    initial_data = workflow.mark_videos_generating(session_id, segment_indexes=segment_indexes)
    background_tasks.add_task(workflow.run_generate_videos_sync, session_id)
    logger.info(f"[API] 已导入工作流的生成任务已提交到后台队列 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message="视频生成任务已启动，正在生成中...",
        data=initial_data,
    )


@router.post("/{session_id}/cancel-videos", response_model=StepResponse)
async def step_4_cancel_videos(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    _session_info: dict = Depends(load_video_session),
):
    """步骤4取消：取消正在进行的视频生成任务"""
    step_result = session_manager.get_step_result(session_id, "generate_videos")
    if not step_result:
        raise HTTPException(status_code=400, detail="视频生成任务尚未开始")

    result_data = step_result['result_data']
    if not result_data.get('_generating', False):
        raise HTTPException(status_code=400, detail="当前没有正在进行的视频生成任务")

    success = session_manager.set_step_cancelled(session_id, "generate_videos", True)
    if not success:
        raise HTTPException(status_code=500, detail="设置取消标志失败")

    return StepResponse(
        success=True,
        message="取消请求已发送，正在停止生成任务...",
        data={"cancelled": True},
    )


@router.post("/{session_id}/restore-videos-backup", response_model=StepResponse)
async def step_4_restore_videos_backup(
    session_id: str,
    _session_info: dict = Depends(load_video_session),
):
    """恢复备份的视频（将 _old_video_path 恢复为 video_path）"""
    result_data = get_workflow().restore_videos_backup(session_id)

    return StepResponse(
        success=True,
        message=f"已恢复 {result_data['success_count']} 个视频的备份",
        data=result_data,
    )

