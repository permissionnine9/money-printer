"""
FastAPI 依赖注入
"""
from functools import lru_cache
from backend.core.persistence.session_manager import SessionManager
from backend.core.agents.workflow_v2 import VideoCreationWorkflowV2


@lru_cache()
def get_session_manager() -> SessionManager:
    """获取会话管理器实例（单例）"""
    return SessionManager()


def get_workflow() -> VideoCreationWorkflowV2:
    """
    获取工作流实例

    Returns:
        VideoCreationWorkflowV2 实例（共享 SessionManager）
    """
    session_manager = get_session_manager()
    return VideoCreationWorkflowV2(session_manager=session_manager)
