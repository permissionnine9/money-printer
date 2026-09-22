"""Agent 步骤运行封装

收敛 agents 层 6 处「prompt 准备 → run_agent → error 抛业务异常 → 解析」模板：
- prompt 可直接传预构建字符串，或传 template+vars 由 PromptManager 渲染
- cwd 非空时授予 READ_ONLY_TOOLS（剧本工作区内自主检索）；mcp_servers 可透传（分集设计写侧工具）
- result.error 统一抛业务异常（由子类注入的 error_cls 决定异常类型）
- parse 回调解析文本；可为 None（调用方自行取 store 状态校验，此时返回 AgentRunResult）
"""
import asyncio
from typing import Callable, Optional

from backend.core.agent_sdk import READ_ONLY_TOOLS, AgentRunOptions, AgentRunResult, run_agent
from backend.core.errors import WorkflowError
from backend.core.services.prompt_manager import get_prompt_manager

OnEvent = Callable[..., None]


class AgentStepService:
    """单次 agent 步骤运行封装"""

    def __init__(self, error_cls: type[WorkflowError] = WorkflowError):
        self.error = error_cls

    async def run(
        self,
        label: str,
        *,
        prompt: Optional[str] = None,
        template: Optional[str] = None,
        variables: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        max_turns: int = 2,
        cwd: Optional[str] = None,
        mcp_servers: Optional[dict] = None,
        thinking_tokens: Optional[int] = None,
        skills: Optional[list[str]] = None,
        interrupt: Optional[asyncio.Event] = None,
        on_event: Optional[OnEvent] = None,
        parse: Optional[Callable[[str], object]] = None,
    ):
        """运行一次 agent；label 用于拼错误消息（如「大纲生成失败: ...」）"""
        if prompt is None:
            if template is None:
                raise ValueError("prompt 与 template 至少传一个")
            prompt = get_prompt_manager().render(template, variables or {})
        result = await run_agent(
            AgentRunOptions(
                prompt=prompt,
                system_prompt=system_prompt,
                max_turns=max_turns,
                tools=READ_ONLY_TOOLS if cwd else None,
                mcp_servers=mcp_servers,
                cwd=cwd,
                thinking_tokens=thinking_tokens,
                skills=skills,
                interrupt=interrupt,
            ),
            on_event,
        )
        if result.error:
            # interrupted=用户主动取消：带结构化 reason，registry 透传给前端区分「已取消/失败」
            raise self.error(f"{label}失败: {result.error}", reason="cancelled" if result.interrupted else "")
        if parse is None:
            return result
        return parse(result.text)
