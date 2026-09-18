"""
工作流步骤 API（视频工作流 4 步）

1. select_episode      从剧本选集
2. storyboard_outline  分镜大纲（生成/编辑，AgentRunRegistry 观流）
3. segment_management  分镜管理（分镜配置 / 提示词生成 / 完成标记）
4. generate_videos     视频生成（后台任务 + 轮询）
"""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from backend.schemas.steps import (
    SelectEpisodeRequest,
    StoryboardOutlineGenerateRequest,
    StoryboardOutlineUpdateRequest,
    SegmentConfigUpdateRequest,
    StepResponse,
)
from backend.deps import get_session_manager, get_storyboard_workflow, get_workflow
from backend.core.persistence.session_manager import SessionManager
from backend.core.agents.storyboard import StoryboardError, StoryboardWorkflow
from backend.core.agents.workflow_v2 import VideoCreationWorkflowV2
from backend.core.agent_sdk import get_run_registry

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_session(session_id: str, session_manager: SessionManager) -> dict:
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return session_info


@router.post("/{session_id}/select-episode", response_model=StepResponse)
async def step_1_select_episode(
    session_id: str,
    request: SelectEpisodeRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤1：从剧本选集（绑定分集设计与视频参数）"""
    logger.info(f"[API] 步骤1 - 从剧本选集 - 会话: {session_id[:8]}... 分集: {request.episode_id}")

    _require_session(session_id, session_manager)

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
):
    """步骤2：生成分镜大纲 → {run_id}（重生成会级联清空分镜配置与提示词）"""
    _require_session(session_id, session_manager)
    can_execute, reason = session_manager.can_execute_step(session_id, "storyboard_outline")
    if not can_execute:
        raise HTTPException(status_code=400, detail=reason or "请先完成步骤1：从剧本选集")

    workflow = get_storyboard_workflow()
    extra_prompt = (body.extra_prompt if body else "") or ""

    def factory(on_event, interrupt):
        return workflow.generate_outline(session_id, extra_prompt, on_event, interrupt)

    run_id = get_run_registry().start("storyboard_outline", factory)
    return {"success": True, "data": {"run_id": run_id}}


@router.put("/{session_id}/storyboard-outline")
async def update_storyboard_outline(
    session_id: str,
    body: StoryboardOutlineUpdateRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤2：保存人工编辑的导图（只改 mindmap，不动分镜列表）"""
    _require_session(session_id, session_manager)
    try:
        result = get_storyboard_workflow().update_outline(session_id, body.mindmap)
    except StoryboardError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "data": result}


# ==================== 步骤 3：分镜管理 ====================

@router.put("/{session_id}/storyboard-segments/{index}/config")
async def update_segment_config(
    session_id: str,
    index: int,
    body: SegmentConfigUpdateRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤3：更新分镜配置（分镜形式 / overlap；变化会清空该分镜已生成的提示词）"""
    _require_session(session_id, session_manager)
    try:
        result = get_storyboard_workflow().update_segment_config(
            session_id, index, body.model_dump(exclude_none=True),
        )
    except StoryboardError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "data": result}


@router.get("/{session_id}/storyboard-segments/{index}/prompt-context")
async def get_segment_prompt_context(
    session_id: str,
    index: int,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤3：分镜提示词生成弹窗的上下文预览（剧本大纲/本集脚本/分镜大纲/overlap 信息）"""
    _require_session(session_id, session_manager)
    try:
        result = get_storyboard_workflow().build_prompt_context(session_id, index)
    except StoryboardError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "data": result}


@router.post("/{session_id}/storyboard-segments/{index}/generate-prompt")
async def generate_segment_prompt(
    session_id: str,
    index: int,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤3：用 video-prompt skill 生成分镜提示词 → {run_id}（仅全能参考模式）"""
    _require_session(session_id, session_manager)
    workflow = get_storyboard_workflow()

    def factory(on_event, interrupt):
        return workflow.generate_segment_prompt(session_id, index, on_event, interrupt)

    run_id = get_run_registry().start(f"segment_prompt_{index}", factory)
    return {"success": True, "data": {"run_id": run_id}}


@router.post("/{session_id}/segment-management/complete", response_model=StepResponse)
async def complete_segment_management(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤3：完成分镜配置（推进到步骤4：视频生成）"""
    _require_session(session_id, session_manager)
    try:
        result = get_storyboard_workflow().complete_segment_management(session_id)
    except StoryboardError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return StepResponse(success=True, message="分镜配置已完成", data=result)


# ==================== 步骤 4：生成视频 ====================

def _build_initial_videos(segments: list[dict]) -> list[dict]:
    """构建视频生成初始状态（所有视频标记为 pending）"""
    return [
        {
            "segment_index": segment.get("index", 0),
            "video_id": "",
            "video_path": "",
            "duration": 0.0,
            "prompt": "",
            "task_status": "pending",
        }
        for segment in segments
    ]


@router.post("/{session_id}/videos", response_model=StepResponse)
async def step_4_generate_videos(
    session_id: str,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤4：生成视频（后台任务 + 前端轮询）"""
    logger.info(f"[API] 步骤4 - 生成视频 - 会话: {session_id[:8]}...")

    _require_session(session_id, session_manager)

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

    async def execute_step():
        logger.info(f"[API] 后台任务启动 - 开始生成视频 - 会话: {session_id[:8]}...")
        wf = get_workflow()
        await wf.step_generate_videos(session_id)
        logger.info(f"[API] 后台任务完成 - 视频生成完成 - 会话: {session_id[:8]}...")

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)
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
):
    """步骤4取消：取消正在进行的视频生成任务"""
    _require_session(session_id, session_manager)

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
):
    """步骤4重新生成：保留旧视频数据作为备份，标记为待重新生成状态"""
    logger.info(f"[API] 步骤4 - 重新生成视频 - 会话: {session_id[:8]}...")

    _require_session(session_id, session_manager)

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
    initial_videos = []
    for segment in segments:
        seg_idx = segment.get("index", 0)
        existing_video = next((v for v in existing_videos if v.get('segment_index') == seg_idx), None)
        if existing_video and existing_video.get('video_path'):
            initial_videos.append({
                "segment_index": seg_idx,
                "video_id": "",
                "video_path": "",
                "duration": 0.0,
                "prompt": "",
                "task_status": "pending",
                "_old_video_path": existing_video.get('video_path'),  # 备份旧路径
                "_old_video_id": existing_video.get('video_id', ''),
            })
        else:
            initial_videos.append({
                "segment_index": seg_idx,
                "video_id": "",
                "video_path": "",
                "duration": 0.0,
                "prompt": "",
                "task_status": "pending",
            })

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

    async def execute_step():
        logger.info(f"[API] 后台任务启动 - 开始重新生成视频 - 会话: {session_id[:8]}...")
        wf = get_workflow()
        await wf.step_generate_videos(session_id)
        logger.info(f"[API] 后台任务完成 - 视频重新生成完成 - 会话: {session_id[:8]}...")

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)

    message = "视频重新生成任务已启动，正在生成中..."
    if backed_up_count > 0:
        message += f"（已保留 {backed_up_count} 个旧视频作为备份）"

    return StepResponse(success=True, message=message, data=initial_data)


@router.post("/{session_id}/restore-videos-backup", response_model=StepResponse)
async def step_4_restore_videos_backup(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """恢复备份的视频（将 _old_video_path 恢复为 video_path）"""
    _require_session(session_id, session_manager)

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


@router.post("/{session_id}/regenerate-single-video/{segment_index}", response_model=StepResponse)
async def step_4_regenerate_single_video(
    session_id: str,
    segment_index: int,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤4重新生成单个视频：仅重新生成指定分片的视频（保留旧视频作为备份）"""
    logger.info(f"[API] 步骤4 - 重新生成单个视频 (分片 {segment_index}) - 会话: {session_id[:8]}...")

    _require_session(session_id, session_manager)

    if not session_manager.is_step_completed(session_id, "generate_videos"):
        raise HTTPException(status_code=400, detail="步骤4尚未完成，请先完成视频生成")
    if not session_manager.is_step_completed(session_id, "segment_management"):
        raise HTTPException(status_code=400, detail="请先完成步骤3：分镜管理")

    existing_result = session_manager.get_step_result(session_id, "generate_videos")
    result_data = existing_result['result_data']
    generated_videos = result_data.get('generated_videos', []) if existing_result else []

    target_video = None
    for video in generated_videos:
        if video.get('segment_index') == segment_index:
            target_video = video
            break

    if target_video is None:
        raise HTTPException(status_code=404, detail=f"未找到分片 {segment_index} 的视频数据")

    if target_video.get('video_path'):
        target_video['_old_video_path'] = target_video['video_path']
        target_video['_old_video_id'] = target_video.get('video_id', '')

    target_video['video_id'] = ""
    target_video['video_path'] = ""
    target_video['prompt'] = ""
    target_video['task_status'] = "pending"

    result_data['_generating'] = True
    result_data['_success'] = False
    session_manager.update_step_result(session_id, "generate_videos", result_data)

    async def execute_single_video_generation():
        logger.info(f"[API] 后台任务启动 - 开始重新生成单个视频 (分片 {segment_index}) - 会话: {session_id[:8]}...")
        try:
            workflow = get_workflow()

            frames_result = session_manager.get_step_result(session_id, "generate_segment_frames")
            selected_episode = workflow.get_selected_episode(session_id)

            from backend.core.models import SegmentFrame, ScriptSegment, VideoParams

            raw_frames = frames_result['result_data'].get('segment_frames', []) if frames_result else []
            cleaned_frames = []
            for frame in raw_frames:
                cleaned_frame = {}
                for key, value in frame.items():
                    cleaned_frame[key] = "" if value is None else value
                cleaned_frames.append(cleaned_frame)
            segment_frames = [SegmentFrame(**frame) for frame in cleaned_frames]
            segment_scripts = [ScriptSegment(**seg) for seg in workflow._get_video_segments(session_id)]
            params = selected_episode['video_params']
            video_params = VideoParams(**params)

            segment = None
            frame = None
            seg_list_index = -1
            for i, seg in enumerate(segment_scripts):
                if seg.index == segment_index:
                    segment = seg
                    seg_list_index = i
                    break
            for f in segment_frames:
                if f.segment_index == segment_index:
                    frame = f
                    break

            if not segment or not frame or not frame.first_image_path:
                # 标记为失败
                result_data = session_manager.get_step_result(session_id, "generate_videos")['result_data']
                for video in result_data['generated_videos']:
                    if video.get('segment_index') == segment_index:
                        video['task_status'] = "failed"
                        video['video_path'] = "生成失败: 缺少分片数据或首尾帧"
                        break
                result_data['_generating'] = False
                result_data['failed_count'] = result_data.get('failed_count', 0) + 1
                session_manager.update_step_result(session_id, "generate_videos", result_data)
                logger.error(f"[API] 分片 {segment_index} 缺少数据或首尾帧 - 会话: {session_id[:8]}...")
                return

            prev_segment = segment_scripts[seg_list_index - 1] if seg_list_index > 0 else None
            next_segment = segment_scripts[seg_list_index + 1] if seg_list_index < len(segment_scripts) - 1 else None

            video = await workflow.video_service.generate_video_from_frames(
                segment,
                frame.first_image_path,
                frame.last_image_path,
                video_params,
                total_segments=len(segment_scripts),
                extra_prompt="",
                prev_segment=prev_segment,
                next_segment=next_segment,
            )

            if not hasattr(video, 'task_status') or not video.task_status:
                if video.video_path and not video.video_path.startswith("生成失败"):
                    video.task_status = "completed"
                elif video.video_path and video.video_path.startswith("生成失败"):
                    video.task_status = "failed"
                else:
                    video.task_status = "pending"

            result_data = session_manager.get_step_result(session_id, "generate_videos")['result_data']
            for i, v in enumerate(result_data['generated_videos']):
                if v.get('segment_index') == segment_index:
                    result_data['generated_videos'][i] = video.model_dump()
                    break

            success_count = sum(1 for v in result_data['generated_videos'] if v.get('task_status') == 'completed')
            failed_count = sum(1 for v in result_data['generated_videos'] if v.get('task_status') == 'failed')

            result_data['success_count'] = success_count
            result_data['failed_count'] = failed_count
            result_data['_generating'] = False
            result_data['_success'] = (failed_count == 0)

            session_manager.update_step_result(session_id, "generate_videos", result_data)
            logger.info(f"[API] 后台任务完成 - 单个视频重新生成完成 (分片 {segment_index}) - 会话: {session_id[:8]}...")

        except Exception as e:
            logger.error(f"[API] 单个视频重新生成失败 (分片 {segment_index}): {e}")
            result_data = session_manager.get_step_result(session_id, "generate_videos")['result_data']
            for video in result_data['generated_videos']:
                if video.get('segment_index') == segment_index:
                    video['task_status'] = "failed"
                    video['video_path'] = f"生成失败: {str(e)}"
                    break
            result_data['_generating'] = False
            session_manager.update_step_result(session_id, "generate_videos", result_data)

    def run_async_task():
        asyncio.run(execute_single_video_generation())

    background_tasks.add_task(run_async_task)
    logger.info(f"[API] 单个视频重新生成任务已提交到后台队列 (分片 {segment_index}) - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message=f"视频 {segment_index + 1} 重新生成任务已启动",
        data=result_data,
    )
