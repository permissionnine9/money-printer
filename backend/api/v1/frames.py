"""
首尾帧管理 API
"""
from fastapi import APIRouter, Depends, HTTPException

from backend.schemas.frames import (
    FrameRegenerateRequest,
    FrameUploadRequest,
    FrameReuseRequest,
    FrameResponse,
)
from backend.schemas.steps import OverlapUpdateRequest
from backend.deps import get_session_manager, get_workflow
from backend.core.persistence.session_manager import SessionManager

router = APIRouter()


@router.put("/{session_id}/overlap", response_model=FrameResponse)
async def update_overlap(
    session_id: str,
    request: OverlapUpdateRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """更新相邻分片之间的 overlap 参数（供视频生成时段间过渡衔接）"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    workflow = get_workflow()
    result = workflow.update_overlap(session_id, request.overlap_seconds)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "更新失败"))

    return FrameResponse(success=True, message=result.get("message", "overlap 已更新"))


@router.post("/{session_id}/{segment_index}/regenerate", response_model=FrameResponse)
async def regenerate_frame(
    session_id: str,
    segment_index: int,
    request: FrameRegenerateRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """重新生成首尾帧"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    
    workflow = get_workflow()

    # 重新生成指定分片的首尾帧
    result = await workflow.regenerate_frame(
        session_id,
        segment_index,
        request.frame_type,
        custom_prompt=request.custom_prompt or "",
        reference_images=request.reference_images
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "重新生成失败"))
    
    return FrameResponse(
        success=True,
        message=result.get("message", "重新生成成功"),
        frame_path=result.get("image_path"),
    )


@router.post("/{session_id}/{segment_index}/upload", response_model=FrameResponse)
async def upload_frame(
    session_id: str,
    segment_index: int,
    request: FrameUploadRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """上传替换首尾帧"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    
    workflow = get_workflow()
    
    # 使用 replace_frame 方法更新首尾帧路径
    result = workflow.replace_frame(session_id, segment_index, request.frame_type, request.image_path)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "更新帧失败"))
    
    return FrameResponse(
        success=True,
        message=result.get("message", "帧已更新"),
        frame_path=request.image_path,
    )


@router.post("/{session_id}/{segment_index}/reuse", response_model=FrameResponse)
async def reuse_frame(
    session_id: str,
    segment_index: int,
    request: FrameReuseRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """复用帧（支持从任意分片复制）"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    workflow = get_workflow()

    # 如果指定了源分片索引，使用 copy_frame_from 方法
    if request.source_segment_index is not None:
        # 确定源帧类型，如果未指定则默认与目标帧类型相同
        source_frame_type = request.source_frame_type or request.frame_type
        result = workflow.copy_frame_from(
            session_id,
            segment_index,
            request.frame_type,
            request.source_segment_index,
            source_frame_type
        )
    else:
        # 否则使用原有的相邻分片复用逻辑
        result = workflow.reuse_adjacent_frame(session_id, segment_index, request.frame_type)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "复用帧失败"))

    return FrameResponse(
        success=True,
        message=result.get("message", "帧已复用"),
        frame_path=result.get("image_path"),
    )


@router.post("/{session_id}/{segment_index}/use-video-snapshot", response_model=FrameResponse)
async def use_video_snapshot(
    session_id: str,
    segment_index: int,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """设置分片使用上一个分片视频的结尾快照作为首帧

    这会将分片的 first_frame_mode 设置为 'use_video_snapshot'，
    表示在视频生成阶段需要等待上一个分片的视频生成完成，
    然后截取最后一帧作为当前分片的首帧。
    """
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    workflow = get_workflow()

    # 设置使用视频快照模式
    result = workflow.set_use_video_snapshot(session_id, segment_index)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "设置失败"))

    return FrameResponse(
        success=True,
        message=result.get("message", "已设置为使用上一视频快照"),
        step_completed=result.get("step_completed", False),
    )


@router.post("/{session_id}/check-completion", response_model=FrameResponse)
async def check_frames_completion(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """检查步骤5是否已完成

    根据当前的首尾帧配置和分片的视频生成模式，
    检查步骤5（生成首尾帧）是否可以被认为是已完成的。

    支持的特殊模式：
    - 首帧+参考图模式：只需要首帧，不需要尾帧
    - 视频快照模式：首帧在视频生成阶段获取，只需要尾帧
    """
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查步骤5是否已完成
    step_completed = session_manager.check_and_update_frames_step_status(session_id)

    if step_completed:
        return FrameResponse(
            success=True,
            message="步骤5已完成：所有首尾帧已配置完成",
            step_completed=True,
        )
    else:
        return FrameResponse(
            success=True,
            message="步骤5未完成：还有首尾帧需要生成",
            step_completed=False,
        )
