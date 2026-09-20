"""
会话管理 API
"""
from fastapi import APIRouter, Depends
from typing import List
import re
import uuid

from backend.schemas.sessions import (
    SessionResponse,
    SessionDetailResponse,
    SessionListResponse,
)
from backend.deps import get_session_manager, get_workspace_store, load_video_session
from backend.core.persistence.session_manager import SessionManager
from backend.core.services.step_payload import script_title, video_step_results

router = APIRouter()


def _episode_number(episode_id: str | None) -> int | None:
    """从 episode_id（如 ep_01）解析集数，格式不符返回 None"""
    m = re.match(r"^ep_(\d+)$", episode_id or "")
    return int(m.group(1)) if m else None


@router.post("", response_model=SessionResponse, status_code=201)
def create_session(
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
def list_sessions(
    session_manager: SessionManager = Depends(get_session_manager),
):
    """获取所有会话列表（旧版 5/7 步会话标记 legacy，前端隐藏）"""
    sessions = session_manager.list_sessions()
    script_title_cache: dict[str, str] = {}

    session_responses = []
    for session in sessions:

        # 剧本会话走 /script-sessions 接口，不混入视频会话列表
        # （全新空剧本会话 completed_steps 为空、legacy=False，不过滤会漏进前端列表）
        if session.get("workflow_type") == "script":
            continue
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
        # 引用的剧本/分集名称（选集步骤结果 + 剧本会话大纲根节点）
        select_result = all_results.get("select_episode") or {}
        script_session_id = select_result.get("script_session_id")
        if script_session_id and script_session_id not in script_title_cache:
            script_title_cache[script_session_id] = script_title(
                get_workspace_store(), script_session_id,
            )
        session_responses.append(
            SessionResponse(
                session_id=session["session_id"],
                created_at=session["created_at"],
                updated_at=session["updated_at"],
                current_step=session.get("current_step") or session_manager.STEPS[0],
                status=session.get("status") or "active",
                completed_steps=completed_steps,
                legacy=legacy,
                script_session_id=script_session_id or "",
                script_title=script_title_cache.get(script_session_id, "") if script_session_id else "",
                episode_title=select_result.get("episode_title") or "",
                episode_number=_episode_number(select_result.get("episode_id")),
            )
        )

    return SessionListResponse(sessions=session_responses, total=len(session_responses))


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    session_info: dict = Depends(load_video_session),
):
    """获取会话详情"""
    return SessionDetailResponse(
        session_id=session_info["session_id"],
        created_at=session_info["created_at"],
        updated_at=session_info["updated_at"],
        current_step=session_info["current_step"],
        status=session_info["status"],
        completed_steps=session_manager.get_completed_steps(session_id),
        step_results=video_step_results(session_manager, get_workspace_store(), session_id),
    )


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    _session_info: dict = Depends(load_video_session),
):
    """删除会话"""
    session_manager.delete_session(session_id)
    return {"success": True, "message": f"会话 {session_id} 已删除"}
