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
from backend.schemas.script import CreateVideoSessionFromScriptRequest
from backend.deps import get_session_manager
from backend.core.persistence.session_manager import SessionManager
from backend.deps import get_script_manager, get_script_session_manager

router = APIRouter()


@router.post("/from-script", response_model=SessionResponse, status_code=201)
async def create_session_from_script(
    body: CreateVideoSessionFromScriptRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """从剧本选集创建视频工作流会话"""
    script_sm = get_script_session_manager()
    script_info = script_sm.get_session(body.script_session_id)
    if not script_info or script_info.get("workflow_type") != "script":
        raise HTTPException(status_code=404, detail=f"剧本会话 {body.script_session_id} 不存在")
    if not script_sm.is_step_completed(body.script_session_id, "episode_design"):
        raise HTTPException(status_code=400, detail="该剧本会话的分集设计尚未完成")
    episode = get_script_manager().get_episode(body.script_session_id, body.episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail=f"分集 {body.episode_id} 不存在")

    session_id = str(uuid.uuid4())
    session_manager.create_session(
        session_id,
        workflow_type="video",
        script_session_id=body.script_session_id,
        source_episode_id=body.episode_id,
    )
    session_info = session_manager.get_session(session_id)
    return SessionResponse(
        session_id=session_info["session_id"],
        created_at=session_info["created_at"],
        updated_at=session_info["updated_at"],
        current_step=session_info["current_step"],
        status=session_info["status"],
        completed_steps=session_manager.get_completed_steps(session_id),
    )


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
    """获取所有会话列表（旧版 5/7 步会话标记 legacy，前端隐藏）"""
    sessions = session_manager.list_sessions()

    session_responses = []
    for session in sessions:
        completed_steps = session_manager.get_completed_steps(session["session_id"])
        all_results = session_manager.get_all_step_results(session["session_id"])
        # 旧版 7 步会话（无 select_episode 结果且 step_results 非空）
        # 与旧版 5 步会话（含已删除的旧步骤结果）均不兼容新 4 步工作流
        has_select = "select_episode" in all_results
        has_legacy_steps = any(
            k in all_results
            for k in (
                "generate_segment_scripts",
                "generate_episode_reference_images",
                "generate_segment_frames",
            )
        )
        legacy = bool(completed_steps) and (not has_select or has_legacy_steps)
        session_responses.append(
            SessionResponse(
                session_id=session["session_id"],
                created_at=session["created_at"],
                updated_at=session["updated_at"],
                current_step=session.get("current_step") or session_manager.STEPS[0],
                status=session.get("status") or "active",
                completed_steps=completed_steps,
                legacy=legacy,
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
    for step_name in session_manager.STEPS:
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
