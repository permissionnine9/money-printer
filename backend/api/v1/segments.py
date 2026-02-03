"""
分片编辑 API
"""
from fastapi import APIRouter, Depends, HTTPException

from backend.schemas.segments import (
    SegmentUpdateRequest,
    SegmentResponse,
    SegmentAddRequest,
)
from backend.deps import get_session_manager, get_workflow
from core.persistence.session_manager import SessionManager
from core.models.video_models import ScriptSegment

router = APIRouter()


@router.put("/{session_id}/{index}", response_model=SegmentResponse)
async def update_segment(
    session_id: str,
    index: int,
    request: SegmentUpdateRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """更新分片脚本"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    
    workflow = get_workflow()
    
    # 创建更新后的分片
    updated_segment = ScriptSegment(
        index=index,
        content=request.content,
        duration=request.duration,
        action=request.action,
        camera_movement=request.camera_movement,
        composition=request.composition,
        atmosphere=request.atmosphere,
    )
    
    # 更新分片
    result = workflow.update_segment(session_id, index, updated_segment)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "更新失败"))
    
    return SegmentResponse(success=True, message=result.get("message", "更新成功"))


@router.delete("/{session_id}/{index}", response_model=SegmentResponse)
async def delete_segment(
    session_id: str,
    index: int,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """删除分片脚本"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    
    workflow = get_workflow()
    
    result = workflow.delete_segment(session_id, index)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "删除失败"))
    
    return SegmentResponse(success=True, message=result.get("message", "删除成功"))


@router.post("/{session_id}/add", response_model=SegmentResponse)
async def add_segment(
    session_id: str,
    request: SegmentAddRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """添加新分片"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    
    workflow = get_workflow()
    
    # 创建新分片
    new_segment = ScriptSegment(
        index=-1,  # 将由 add_segment 方法自动设置
        content=request.content,
        duration=request.duration,
        action=request.action,
        camera_movement=request.camera_movement,
        composition=request.composition,
        atmosphere=request.atmosphere,
    )
    
    result = workflow.add_segment(session_id, new_segment.model_dump(), request.insert_after)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "添加失败"))
    
    return SegmentResponse(success=True, message=result.get("message", "添加成功"))
