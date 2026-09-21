"""重生成级联清理（services 层编排：跨 sm / store / scm 三个持久化组件）

SessionManager 不持有 store/scm，级联清理放 services 层以避免持久化层反向依赖。
"""
from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.session_manager import SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore


def cascade_regenerate(
    sm: SessionManager,
    store: WorkspaceStore,
    scm: ScriptManager,
    session_id: str,
    step: str,
) -> None:
    """重生成级联清理：下游步骤结果（DB）+ 工作区分集/实体文件 + DB 核心素材/素材图任务

    已完成且有图的核心素材保留为历史素材（第 4 步素材库可复用）；未完成行删除。
    """
    sm.clear_steps_after(session_id, step)
    store.delete_story_content(session_id)
    scm.delete_script_data(session_id, keep_completed_lookbooks=True)
