"""步骤型工作流公共基类

收敛 ScriptWorkflow / StoryboardWorkflow 重复的：
- OnEvent 类型别名与事件回退
- 步骤数据读取守卫（未完成抛业务异常）
- 前置步骤校验
"""
from typing import Callable

from backend.core.agent_sdk import AgentEvent
from backend.core.persistence import SessionManager
from backend.core.services.prompt_manager import get_prompt_manager

OnEvent = Callable[[AgentEvent], None]


class StepWorkflowBase:
    """步骤型工作流基类

    子类需声明 `Error = <业务异常类>`（守卫抛出，API 层转 400 detail）。
    """

    Error: type[Exception] = RuntimeError

    def __init__(self, session_manager: SessionManager):
        self.sm = session_manager
        self.prompts = get_prompt_manager()

    def require_step_data(self, session_id: str, step_name: str, *, not_started_message: str = "") -> dict:
        """读取步骤结果数据，未完成则抛业务异常"""
        step = self.sm.get_step_result(session_id, step_name)
        if not step or not step.get("result_data"):
            raise self.Error(not_started_message or f"步骤尚未完成: {step_name}")
        return step["result_data"]

    def ensure_can_execute(self, session_id: str, step_name: str) -> None:
        """校验前置步骤已完成，不满足则抛业务异常"""
        ok, reason = self.sm.can_execute_step(session_id, step_name)
        if not ok:
            raise self.Error(reason)
