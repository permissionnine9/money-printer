"""Claude Agent SDK 封装

基于 ClaudeSDKClient（进程内 MCP 工具必须用 Client 而非 query()），
将 SDK 消息流归一为 AgentEvent，支持 resume 多轮会话与 interrupt 取消。

移植自 ../annto-knowledge/backend/lib/claude-agent-sdk-wrapper.ts（Python 版差异：
- query() → ClaudeSDKClient（进程内 MCP server 需要）
- AbortController → asyncio.Event + client.interrupt()
- session_id 从 ResultMessage 捕获（SDK 自动落盘 ~/.claude/projects/）
"""
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLIConnectionError,
    ProcessError,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from backend.core.agent_sdk.events import AgentEvent
from backend.core.agent_sdk.model_env import build_agent_env

logger = logging.getLogger(__name__)

DEFAULT_MAX_TURNS = 40
DEFAULT_THINKING_TOKENS = 6000
# SDK 读 CLI 子进程 stdout（stream-json）的单条消息上限：Agent Read 图片时
# tool_result 回显整图 base64，SDK 默认 1MB 会被 2K/4K 原图撑爆
# （报错 "JSON message exceeded maximum buffer size of 1048576 bytes"）
MAX_STREAM_BUFFER_SIZE = 16 * 1024 * 1024

# 文件化工作区的只读检索工具（配合 cwd 锁定剧本目录，释放 Agent 自主检索能力；
# 写入仍由后端结构化落盘，Agent 无写权限）。
# 边界说明：权限采用 dontAsk 模式 + allowed_tools 路径规则（Read/Grep/Glob 仅
# 放行 cwd 目录内，绝对路径越界由 CLI 权限系统硬拒绝；MCP 工具按 server 白名单放行）。
READ_ONLY_TOOLS = ["Read", "Grep", "Glob"]


def _build_allowed_tools(cwd: Optional[str], mcp_servers: Optional[dict]) -> list[str]:
    """构造 dontAsk 模式下的自动放行清单：工作区路径规则 + MCP server 白名单

    Read/Grep/Glob 必须带路径 specifier（裸 "Grep" 会放行任意 path 参数，可越界检索）；
    绝对路径规则用 // 前缀（gitignore 风格，见 Claude Code 权限规则语法）。
    """
    allowed: list[str] = []
    if cwd:
        root = str(Path(cwd).resolve()).rstrip("/")
        allowed += [f"Read(//{root}/**)", f"Grep(//{root}/**)", f"Glob(//{root}/**)"]
    for server_name in (mcp_servers or {}):
        allowed.append(f"mcp__{server_name}")
    return allowed


@dataclass
class AgentRunOptions:
    """一次 agent 运行的全部选项"""
    prompt: str
    system_prompt: Optional[str] = None
    max_turns: int = DEFAULT_MAX_TURNS
    # 默认不授予任何内置工具（含联网），能力只能由 mcp_servers 显式注入；
    # 传 READ_ONLY_TOOLS 可开放工作区文件检索（需配合 cwd）
    tools: Optional[list[str]] = None
    mcp_servers: Optional[dict] = None
    # 工作目录（Read/Grep/Glob 的硬边界锚点：仅该目录内放行，越界路径由 CLI 权限系统拒绝；
    # 同时作为相对路径基准；缺省继承后端进程 cwd）
    cwd: Optional[str] = None
    # 多轮会话：要 resume 的 agent session_id（首轮留空由 SDK 生成）
    resume: Optional[str] = None
    # 触发后调用 client.interrupt() 取消运行
    interrupt: Optional[asyncio.Event] = None
    # 额外环境变量（默认继承当前进程 + 注入 agent 模型端点）
    env: Optional[dict[str, str]] = None


@dataclass
class AgentRunResult:
    """一次 agent 运行的结果"""
    text: str = ""
    session_id: str = ""
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    error: Optional[str] = None
    interrupted: bool = False


async def run_agent(
    options: AgentRunOptions,
    on_event: Callable[[AgentEvent], None],
) -> AgentRunResult:
    """运行一次 agent，事件经 on_event 回调流出，返回最终结果"""
    env = options.env or build_agent_env()

    sdk_options = ClaudeAgentOptions(
        system_prompt=options.system_prompt,
        max_turns=options.max_turns,
        tools=options.tools if options.tools is not None else [],
        mcp_servers=options.mcp_servers or {},
        # dontAsk：未在 allowed_tools 白名单内的调用一律硬拒绝（无头模式无人工确认）
        permission_mode="dontAsk",
        allowed_tools=_build_allowed_tools(options.cwd, options.mcp_servers),
        include_partial_messages=True,
        max_thinking_tokens=DEFAULT_THINKING_TOKENS,
        max_buffer_size=MAX_STREAM_BUFFER_SIZE,
        # 隔离模式：禁止子进程加载任何用户级/项目级设置与插件
        setting_sources=[],
        env=env,
        resume=options.resume,
        cwd=options.cwd,
    )

    result = AgentRunResult()
    client = ClaudeSDKClient(options=sdk_options)
    interrupt_watcher: Optional[asyncio.Task] = None

    # 流式累积状态（用于完整 assistant 消息的去重与 result 兜底文本）
    accumulated_text = ""
    accumulated_thinking = ""
    tool_names: dict[str, str] = {}      # tool_use_id → tool name
    tool_inputs: dict[str, str] = {}     # tool_use_id → partial JSON
    index_to_id: dict[int, str] = {}     # content block index → tool_use_id

    def emit(event: AgentEvent) -> None:
        nonlocal accumulated_text, accumulated_thinking
        if event.type == "text_delta":
            accumulated_text += event.delta
        elif event.type == "thinking":
            accumulated_thinking += event.delta
        on_event(event)

    # 提示词透明化：发起 LLM 调用前流出最终渲染后的提示词
    # （形态 A 直跑 SSE / 形态 B registry 缓冲回放统一覆盖，含 run_conversation 多轮）
    emit(AgentEvent(
        type="prompt",
        system_prompt=options.system_prompt or "",
        user_prompt=options.prompt,
        model=env.get("ANTHROPIC_MODEL", ""),
    ))

    try:
        async with client:
            if options.interrupt is not None:
                async def _watch_interrupt() -> None:
                    await options.interrupt.wait()
                    await client.interrupt()
                interrupt_watcher = asyncio.create_task(_watch_interrupt())

            await client.query(options.prompt)

            async for msg in client.receive_messages():
                if isinstance(msg, StreamEvent):
                    _handle_stream_event(msg, emit, tool_names, tool_inputs, index_to_id)
                elif isinstance(msg, AssistantMessage):
                    _handle_assistant(
                        msg, emit,
                        accumulated_text, accumulated_thinking,
                        tool_names, tool_inputs,
                    )
                elif isinstance(msg, UserMessage):
                    _handle_user(msg, emit, tool_names)
                elif isinstance(msg, ResultMessage):
                    if msg.subtype == "success":
                        result.text = msg.result or accumulated_text
                        result.session_id = msg.session_id or ""
                        result.usage = msg.usage or {}
                        result.cost_usd = msg.total_cost_usd or 0.0
                        emit(AgentEvent(
                            type="result",
                            text=result.text,
                            session_id=result.session_id,
                            usage={
                                "input_tokens": result.usage.get("input_tokens", 0),
                                "output_tokens": result.usage.get("output_tokens", 0),
                            },
                        ))
                    else:
                        err = ", ".join(msg.errors or []) or msg.subtype
                        result.error = err
                        emit(AgentEvent(type="error", message=err))
                    # Client 模式下 receive_messages 不会在 result 后自动结束（可多轮 query），必须主动退出
                    break
                elif isinstance(msg, SystemMessage):
                    pass  # init 等系统消息不外发
    except (ProcessError, CLIConnectionError) as e:
        message = str(e) or type(e).__name__
        logger.error(f"[AgentSDK] 进程异常: {message}")
        result.error = message
        emit(AgentEvent(type="error", message=message))
    except asyncio.CancelledError:
        result.interrupted = True
        result.error = "已取消"
        emit(AgentEvent(type="error", message="已取消", reason="cancelled"))
        raise
    finally:
        if interrupt_watcher is not None:
            interrupt_watcher.cancel()

    # interrupt 后 SDK 通常以非 success result 或异常收尾；此处兜底标记
    if options.interrupt is not None and options.interrupt.is_set() and not result.error:
        result.interrupted = True
    if result.interrupted:
        result.error = result.error or "已取消"
    return result


def _handle_stream_event(
    msg: StreamEvent,
    emit: Callable[[AgentEvent], None],
    tool_names: dict[str, str],
    tool_inputs: dict[str, str],
    index_to_id: dict[int, str],
) -> None:
    """处理流式增量事件（include_partial_messages=True）"""
    event = msg.event or {}
    etype = event.get("type")

    if etype == "content_block_start":
        block = event.get("content_block") or {}
        if block.get("type") == "tool_use":
            block_id = block.get("id", "")
            tool_names[block_id] = block.get("name", "")
            tool_inputs.setdefault(block_id, "")
            if event.get("index") is not None:
                index_to_id[event["index"]] = block_id

    elif etype == "content_block_delta":
        delta = event.get("delta") or {}
        dtype = delta.get("type")
        if dtype == "thinking_delta":
            emit(AgentEvent(type="thinking", delta=delta.get("thinking", "")))
        elif dtype == "text_delta":
            emit(AgentEvent(type="text_delta", delta=delta.get("text", "")))
        elif dtype == "input_json_delta":
            block_id = index_to_id.get(event.get("index", -1))
            if block_id:
                tool_inputs[block_id] = tool_inputs.get(block_id, "") + (delta.get("partial_json") or "")


def _handle_assistant(
    msg: AssistantMessage,
    emit: Callable[[AgentEvent], None],
    accumulated_text: str,
    accumulated_thinking: str,
    tool_names: dict[str, str],
    tool_inputs: dict[str, str],
) -> None:
    """处理完整 assistant 消息（与流式增量去重后补发）"""
    for block in msg.content:
        if isinstance(block, ThinkingBlock):
            # 完整消息的思考内容：流式已发过则跳过
            if block.thinking and block.thinking not in accumulated_thinking:
                emit(AgentEvent(type="thinking", delta=block.thinking))
        elif isinstance(block, ToolUseBlock):
            tool_names[block.id] = block.name
            emit(AgentEvent(type="tool_use", id=block.id, tool=block.name, input=block.input or {}))
        elif isinstance(block, TextBlock):
            if block.text and block.text not in accumulated_text:
                emit(AgentEvent(type="text_delta", delta=block.text))


def _handle_user(
    msg: UserMessage,
    emit: Callable[[AgentEvent], None],
    tool_names: dict[str, str],
) -> None:
    """处理 user 消息中的 tool_result 块"""
    content = msg.content
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, ToolResultBlock):
            if isinstance(block.content, str):
                text = block.content
            elif isinstance(block.content, list):
                text = "\n".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in block.content
                )
            else:
                text = ""
            preview = text[:50000] + "..." if len(text) > 50000 else text
            emit(AgentEvent(
                type="tool_result",
                id=block.tool_use_id,
                tool=tool_names.get(block.tool_use_id, block.tool_use_id),
                result_preview=preview,
            ))


# ── 可复用便捷 API（剧本 / 视频 / 未来功能统一调用）─────────────────

async def run_conversation(
    message: str,
    system_prompt: Optional[str] = None,
    agent_session_id: Optional[str] = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    on_event: Optional[Callable[[AgentEvent], None]] = None,
    interrupt: Optional[asyncio.Event] = None,
) -> AgentRunResult:
    """多轮会话一轮（剧本第 1 步盘问等）：内部管理 agent_session_id 的 resume 与新建"""
    return await run_agent(
        AgentRunOptions(
            prompt=message,
            system_prompt=system_prompt,
            resume=agent_session_id,
            max_turns=max_turns,
            interrupt=interrupt,
        ),
        on_event or (lambda e: None),
    )
