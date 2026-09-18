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
    SegmentReferenceImagesUpdateRequest,
    SegmentMaterialGenerateRequest,
    StepResponse,
)
from backend.deps import (
    get_session_manager,
    get_storyboard_workflow,
    get_workflow,
    load_video_session,
    start_agent_run,
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
        "max_segment_duration": request.max_segment_duration,
    }
    result = get_workflow().step_select_episode(
        session_id, request.script_session_id, request.episode_id, video_params,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "选集失败"))

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

    return start_agent_run("storyboard_outline", factory)


@router.put("/{session_id}/storyboard-outline")
async def update_storyboard_outline(
    session_id: str,
    body: StoryboardOutlineUpdateRequest,
    _session_info: dict = Depends(load_video_session),
):
    """步骤2：保存人工编辑的导图（markdown 含 `- 分镜内容` 行，解析后同步 mindmap 与分镜列表）"""
    result = get_storyboard_workflow().update_outline(session_id, body.mindmap)
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
    result = get_storyboard_workflow().update_segment_config(
        session_id, index, body.model_dump(exclude_none=True),
    )
    return {"success": True, "data": result}


@router.get("/{session_id}/material-pool")
async def get_material_pool(
    session_id: str,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：素材池（选择弹窗分组数据：定妆照 / 本集素材 / 其他集素材，不跨 story）"""
    result = get_storyboard_workflow().list_material_pool(session_id)
    return {"success": True, "data": result}


@router.put("/{session_id}/storyboard-segments/{index}/reference-images")
async def update_segment_reference_images(
    session_id: str,
    index: int,
    body: SegmentReferenceImagesUpdateRequest,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：保存分镜参考素材图（全量覆盖；换图会清空该分镜已生成的提示词）"""
    result = get_storyboard_workflow().update_segment_reference_images(
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
    workflow.validate_segment_material_request(
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

    return start_agent_run(f"segment_material_{index}", factory)


@router.get("/{session_id}/storyboard-segments/{index}/prompt-context")
async def get_segment_prompt_context(
    session_id: str,
    index: int,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：分镜提示词生成弹窗的上下文预览（剧本大纲/本集脚本/分镜大纲/overlap 信息）"""
    result = get_storyboard_workflow().build_prompt_context(session_id, index)
    return {"success": True, "data": result}


@router.post("/{session_id}/storyboard-segments/{index}/generate-prompt")
async def generate_segment_prompt(
    session_id: str,
    index: int,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：用 video-prompt skill 生成分镜提示词 → {run_id}（仅全能参考模式）"""
    workflow = get_storyboard_workflow()

    def factory(on_event, interrupt):
        return workflow.generate_segment_prompt(session_id, index, on_event, interrupt)

    return start_agent_run(f"segment_prompt_{index}", factory)


@router.post("/{session_id}/segment-management/complete", response_model=StepResponse)
async def complete_segment_management(
    session_id: str,
    _session_info: dict = Depends(load_video_session),
):
    """步骤3：完成分镜配置（推进到步骤4：视频生成）"""
    result = get_storyboard_workflow().complete_segment_management(session_id)
    return StepResponse(success=True, message="分镜配置已完成", data=result)


# ==================== 步骤 4：生成视频 ====================

def _initial_video(segment_index: int, old: dict | None = None) -> dict:
    """构建单个视频的 pending 初始状态；old 有旧视频时保留备份字段"""
    video = {
        "segment_index": segment_index,
        "video_id": "",
        "video_path": "",
        "duration": 0.0,
        "prompt": "",
        "task_status": "pending",
    }
    if old and old.get("video_path"):
        video["_old_video_path"] = old.get("video_path")  # 备份旧路径
        video["_old_video_id"] = old.get("video_id", "")
    return video


def _build_initial_videos(segments: list[dict], existing_videos: list[dict] | None = None) -> list[dict]:
    """构建视频生成初始状态（所有视频标记为 pending；有旧视频的保留备份）"""
    existing_videos = existing_videos or []
    initial = []
    for segment in segments:
        seg_idx = segment.get("index", 0)
        existing = next((v for v in existing_videos if v.get("segment_index") == seg_idx), None)
        initial.append(_initial_video(seg_idx, existing))
    return initial


def _submit_video_background_task(background_tasks: BackgroundTasks, session_id: str, log_label: str) -> None:
    """提交视频生成后台任务（asyncio.run 包装，进度落盘由 workflow 负责）"""
    async def execute_step():
        logger.info(f"[API] 后台任务启动 - 开始{log_label} - 会话: {session_id[:8]}...")
        await get_workflow().step_generate_videos(session_id)
        logger.info(f"[API] 后台任务完成 - {log_label}完成 - 会话: {session_id[:8]}...")

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)


@router.post("/{session_id}/videos", response_model=StepResponse)
async def step_4_generate_videos(
    session_id: str,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
    _session_info: dict = Depends(load_video_session),
):
    """步骤4：生成视频（后台任务 + 前端轮询）"""
    logger.info(f"[API] 步骤4 - 生成视频 - 会话: {session_id[:8]}...")

    can_execute, reason = session_manager.can_execute_step(session_id, "generate_videos")
    if not can_execute:
        raise HTTPException(status_code=400, detail=reason or "请先完成步骤3：分镜管理")

    workflow = get_workflow()
    segments = workflow._get_video_segments(session_id)
    if not segments:
        raise HTTPException(status_code=400, detail="无可用分镜数据，请先生成分镜大纲")

    initial_data = {
        "generated_videos": _build_initial_videos(segments),
        "video_count": len(segments),
        "success_count": 0,
        "failed_count": 0,
        "final_video": None,   # ComfyUI 整段生成的最终视频（完成后填充）
        "_generating": True,   # 标记为生成中
        "_success": False      # 标记为未完成
    }
    session_manager.save_step_result(session_id, "generate_videos", initial_data, success=False)
    logger.info(f"[API] 已保存生成中状态，开始后台生成视频 - 会话: {session_id[:8]}...")

    _submit_video_background_task(background_tasks, session_id, "生成视频")
    logger.info(f"[API] 视频生成任务已提交到后台队列 - 会话: {session_id[:8]}...")

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


@router.post("/{session_id}/regenerate-videos", response_model=StepResponse)
async def step_4_regenerate_videos(
    session_id: str,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
    _session_info: dict = Depends(load_video_session),
):
    """步骤4重新生成：保留旧视频数据作为备份，标记为待重新生成状态"""
    logger.info(f"[API] 步骤4 - 重新生成视频 - 会话: {session_id[:8]}...")

    if not session_manager.is_step_completed(session_id, "generate_videos"):
        raise HTTPException(status_code=400, detail="步骤4尚未完成，请使用正常生成接口")
    if not session_manager.is_step_completed(session_id, "segment_management"):
        raise HTTPException(status_code=400, detail="请先完成步骤3：分镜管理")

    reset = session_manager.reset_current_step(session_id, "generate_videos")
    if not reset:
        raise HTTPException(status_code=500, detail="重置步骤状态失败")

    workflow = get_workflow()
    segments = workflow._get_video_segments(session_id)
    existing_result = session_manager.get_step_result(session_id, "generate_videos")
    existing_videos = existing_result['result_data'].get('generated_videos', []) if existing_result else []

    # 创建待重新生成状态（有旧视频的保留备份）
    initial_videos = _build_initial_videos(segments, existing_videos)
    backed_up_count = sum(1 for v in initial_videos if '_old_video_path' in v)

    initial_data = {
        "generated_videos": initial_videos,
        "video_count": len(initial_videos),
        "success_count": 0,
        "failed_count": 0,
        "_generating": True,
        "_success": False,
        "_backed_up_count": backed_up_count,
    }
    session_manager.save_step_result(session_id, "generate_videos", initial_data, success=False)
    logger.info(f"[API] 已标记为待重新生成状态（保留 {backed_up_count} 个旧视频作为备份）- 会话: {session_id[:8]}...")

    _submit_video_background_task(background_tasks, session_id, "重新生成视频")

    message = "视频重新生成任务已启动，正在生成中..."
    if backed_up_count > 0:
        message += f"（已保留 {backed_up_count} 个旧视频作为备份）"

    return StepResponse(success=True, message=message, data=initial_data)


@router.post("/{session_id}/restore-videos-backup", response_model=StepResponse)
async def step_4_restore_videos_backup(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    _session_info: dict = Depends(load_video_session),
):
    """恢复备份的视频（将 _old_video_path 恢复为 video_path）"""
    existing_result = session_manager.get_step_result(session_id, "generate_videos")
    if not existing_result:
        raise HTTPException(status_code=404, detail="未找到视频数据")

    result_data = existing_result['result_data']
    generated_videos = result_data.get('generated_videos', [])

    restored_count = 0
    for video in generated_videos:
        old_path = video.get('_old_video_path')
        if old_path:
            video['video_path'] = old_path
            video['video_id'] = video.get('_old_video_id', '')
            video['task_status'] = 'completed'
            video['duration'] = 5.0  # 恢复默认时长
            restored_count += 1

    if restored_count == 0:
        raise HTTPException(status_code=400, detail="没有可恢复的备份数据")

    result_data['success_count'] = restored_count
    result_data['failed_count'] = len(generated_videos) - restored_count
    result_data['_generating'] = False
    result_data['_success'] = (restored_count == len(generated_videos))

    session_manager.save_step_result(session_id, "generate_videos", result_data, success=True)
    logger.info(f"[API] 已恢复 {restored_count} 个视频的备份 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message=f"已恢复 {restored_count} 个视频的备份",
        data=result_data,
    )

