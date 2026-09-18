"""
FastAPI 依赖注入
"""
from functools import lru_cache

from fastapi import Depends, HTTPException

from backend.core.agent_sdk import get_run_registry
from backend.core.persistence.session_manager import (
    SCRIPT_STEPS,
    VIDEO_STEPS,
    SessionManager,
)
from backend.core.persistence.model_manager import ModelManager
from backend.core.persistence.script_manager import ScriptManager
from backend.core.agents.storyboard import StoryboardWorkflow
from backend.core.agents.workflow_v2 import VideoCreationWorkflowV2


@lru_cache()
def get_session_manager() -> SessionManager:
    """获取视频会话管理器实例（单例，视频工作流 4 步）"""
    return SessionManager(steps=VIDEO_STEPS)


@lru_cache()
def get_storyboard_workflow() -> StoryboardWorkflow:
    """获取分镜工作流实例（单例，共享视频 SessionManager）"""
    return StoryboardWorkflow(session_manager=get_session_manager())


@lru_cache()
def get_script_session_manager() -> SessionManager:
    """获取剧本会话管理器实例（单例，剧本工作流 4 步）"""
    return SessionManager(steps=SCRIPT_STEPS)


@lru_cache()
def get_script_manager() -> ScriptManager:
    """获取剧本数据管理器实例（单例，与 SessionManager 共用同一个 SQLite）"""
    return ScriptManager()


@lru_cache()
def get_model_manager() -> ModelManager:
    """获取生图模型管理器实例（单例，与 SessionManager 共用同一个 SQLite）"""
    return ModelManager()


def get_workflow() -> VideoCreationWorkflowV2:
    """
    获取工作流实例

    Returns:
        VideoCreationWorkflowV2 实例（共享 SessionManager）
    """
    session_manager = get_session_manager()
    return VideoCreationWorkflowV2(session_manager=session_manager)


# ==================== 实体加载依赖（消除路由层「get_session → 404」样板） ====================

def load_video_session(session_id: str, sm: SessionManager = Depends(get_session_manager)) -> dict:
    """加载视频会话，不存在抛 404"""
    info = sm.get_session(session_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return info


def load_script_session(session_id: str, sm: SessionManager = Depends(get_script_session_manager)) -> dict:
    """加载剧本会话：不存在抛 404，类型不符抛 400"""
    info = sm.get_session(session_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"剧本会话 {session_id} 不存在")
    if info.get("workflow_type") != "script":
        raise HTTPException(status_code=400, detail=f"会话 {session_id} 不是剧本会话")
    return info


# ==================== agent 运行提交（统一 run_id 响应） ====================

def start_agent_run(label: str, factory) -> dict:
    """提交 agent 运行到注册表并返回统一响应 {"success": True, "data": {"run_id": ...}}"""
    run_id = get_run_registry().start(label, factory)
    return {"success": True, "data": {"run_id": run_id}}
