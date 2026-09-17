"""
FastAPI 依赖注入
"""
from functools import lru_cache
from backend.core.persistence.session_manager import SessionManager
from backend.core.persistence.model_manager import ModelManager
from backend.core.agents.workflow_v2 import VideoCreationWorkflowV2


@lru_cache()
def get_session_manager() -> SessionManager:
    """获取会话管理器实例（单例）"""
    return SessionManager()


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
