"""Claude Agent SDK 集成层

可复用组件，供剧本创作 / 视频生成 / 未来功能统一调用，不绑定具体业务。
- wrapper.run_agent / run_conversation: agent 运行入口
- events.AgentEvent: 归一化事件
- registry.get_run_registry(): 后台 run 注册表（SSE 解耦）
- direct.sse_direct_response: SSE 请求内直跑形态（断开即取消）
- model_env.build_agent_env: 模型端点环境注入
"""
from backend.core.agent_sdk.direct import sse_direct_response
from backend.core.agent_sdk.events import AgentEvent
from backend.core.agent_sdk.model_env import AgentModelNotConfiguredError, build_agent_env
from backend.core.agent_sdk.registry import AgentRunRegistry, RunHandle, get_run_registry
from backend.core.agent_sdk.wrapper import (
    READ_ONLY_TOOLS,
    AgentRunOptions,
    AgentRunResult,
    run_agent,
    run_conversation,
)

__all__ = [
    "READ_ONLY_TOOLS",
    "AgentEvent",
    "AgentModelNotConfiguredError",
    "AgentRunOptions",
    "AgentRunResult",
    "AgentRunRegistry",
    "RunHandle",
    "build_agent_env",
    "get_run_registry",
    "run_agent",
    "run_conversation",
    "sse_direct_response",
]
