"""
会话管理 API
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
import uuid

from backend.schemas.sessions import (
    SessionResponse,
    SessionDetailResponse,
    SessionListResponse,
)
from backend.deps import get_session_manager
from core.persistence.session_manager import SessionManager

router = APIRouter()


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    session_manager: SessionManager = Depends(get_session_manager),
):
    """创建新会话"""
    session_id = str(uuid.uuid4())
    session_manager.create_session(session_id)
    
    session_info = session_manager.get_session(session_id)
    return SessionResponse(
        session_id=session_info["session_id"],
        created_at=session_info["created_at"],
        updated_at=session_info["updated_at"],
        current_step=session_info["current_step"],
        status=session_info["status"],
        completed_steps=session_manager.get_completed_steps(session_id),
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    session_manager: SessionManager = Depends(get_session_manager),
):
    """获取所有会话列表"""
    sessions = session_manager.list_sessions()
    
    session_responses = []
    for session in sessions:
        session_responses.append(
            SessionResponse(
                session_id=session["session_id"],
                created_at=session["created_at"],
                updated_at=session["updated_at"],
                current_step=session.get("current_step") or SessionManager.STEPS[0],
                status=session.get("status") or "active",
                completed_steps=session_manager.get_completed_steps(session["session_id"]),
            )
        )
    
    return SessionListResponse(sessions=session_responses, total=len(session_responses))


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """获取会话详情"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    
    # 获取所有步骤结果
    step_results = {}
    for step_name in SessionManager.STEPS:
        result = session_manager.get_step_result(session_id, step_name)
        if result:
            step_results[step_name] = result
    
    return SessionDetailResponse(
        session_id=session_info["session_id"],
        created_at=session_info["created_at"],
        updated_at=session_info["updated_at"],
        current_step=session_info["current_step"],
        status=session_info["status"],
        completed_steps=session_manager.get_completed_steps(session_id),
        step_results=step_results,
    )


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """删除会话"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    
    session_manager.delete_session(session_id)
    return {"success": True, "message": f"会话 {session_id} 已删除"}
