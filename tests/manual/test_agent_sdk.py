"""Phase 0 验证：Agent SDK 基建手工测试

跑通四件事：
1. 一次 agent 运行（流式事件：thinking/text_delta/result）
2. resume 二轮（多轮会话记忆）
3. interrupt 取消
4. 进程内 MCP 工具调用（create_sdk_mcp_server + @tool）

用法: uv run python test_agent_sdk.py
前提: 模型管理已录入 model_type='agent' 的默认模型（Anthropic 协议端点）
"""
import asyncio
import sys

sys.path.insert(0, ".")

from claude_agent_sdk import create_sdk_mcp_server, tool

from backend.core.agent_sdk import (
    AgentEvent,
    AgentModelNotConfiguredError,
    build_agent_env,
    run_conversation,
)
from backend.core.agent_sdk.wrapper import AgentRunOptions, run_agent


def make_collector():
    """收集事件并打印摘要"""
    events: list[AgentEvent] = []

    def on_event(ev: AgentEvent) -> None:
        events.append(ev)
        if ev.type == "thinking":
            print(f"  [thinking] +{len(ev.delta)}字")
        elif ev.type == "text_delta":
            print(f"  [text] {ev.delta}", end="", flush=True)
        elif ev.type == "tool_use":
            print(f"\n  [tool_use] {ev.tool}({ev.input})")
        elif ev.type == "tool_result":
            print(f"  [tool_result] {ev.tool}: {ev.result_preview[:100]}")
        elif ev.type == "result":
            print(f"\n  [result] session={ev.session_id[:16]}... usage={ev.usage}")
        elif ev.type == "error":
            print(f"\n  [error] {ev.message}")

    return events, on_event


async def test_basic_run() -> str:
    print("\n=== 测试 1: 基本运行 + 流式事件 ===")
    events, on_event = make_collector()
    result = await run_agent(
        AgentRunOptions(prompt="用一句话介绍你自己，不要超过30个字。", max_turns=2),
        on_event,
    )
    assert not result.error, f"运行失败: {result.error}"
    assert result.text, "无输出文本"
    assert result.session_id, "未捕获 session_id"
    types = {e.type for e in events}
    assert "result" in types, "缺少 result 事件"
    print(f"  ✓ 文本={result.text!r} session_id={result.session_id[:16]}...")
    return result.session_id


async def test_resume(session_id: str) -> None:
    print("\n=== 测试 2: resume 二轮（多轮记忆） ===")
    _, on_event = make_collector()
    result = await run_conversation(
        message="我上一句话让你做了什么？只回答任务内容本身。",
        agent_session_id=session_id,
        max_turns=2,
        on_event=on_event,
    )
    assert not result.error, f"resume 失败: {result.error}"
    print(f"  ✓ 回答: {result.text!r}")
    assert "介绍" in result.text or "一句话" in result.text, "多轮记忆失效：回答未体现上文"


async def test_interrupt() -> None:
    print("\n=== 测试 3: interrupt 取消 ===")
    _, on_event = make_collector()
    interrupt = asyncio.Event()

    async def fire():
        await asyncio.sleep(3)
        interrupt.set()

    asyncio.get_running_loop().create_task(fire())
    result = await run_agent(
        AgentRunOptions(
            prompt="从 1 数到 100，每个数字一行，慢慢数。",
            max_turns=2,
            interrupt=interrupt,
        ),
        on_event,
    )
    assert result.error, "interrupt 后应有错误标记"
    print(f"  ✓ 取消生效: error={result.error!r}")


@tool(
    "add_numbers",
    "两数相加，返回算式与结果",
    {
        "type": "object",
        "properties": {
            "a": {"type": "integer", "description": "第一个数"},
            "b": {"type": "integer", "description": "第二个数"},
        },
        "required": ["a", "b"],
    },
)
async def add_numbers(args: dict) -> dict:
    a, b = args["a"], args["b"]
    return {"content": [{"type": "text", "text": f"{a} + {b} = {a + b}"}]}


async def test_mcp_tool() -> None:
    print("\n=== 测试 4: 进程内 MCP 工具调用 ===")
    server = create_sdk_mcp_server(
        name="calc",
        version="1.0.0",
        tools=[add_numbers],
    )
    events, on_event = make_collector()
    result = await run_agent(
        AgentRunOptions(
            prompt="请调用工具计算 17 加 25，然后用一句话报出结果。",
            max_turns=4,
            mcp_servers={"calc": server},
        ),
        on_event,
    )
    assert not result.error, f"MCP 运行失败: {result.error}"
    tool_uses = [e for e in events if e.type == "tool_use" and e.tool.endswith("add_numbers")]
    assert tool_uses, "未捕获 add_numbers 工具调用"
    assert "42" in result.text, f"工具结果未体现在回答中: {result.text!r}"
    print("  ✓ 工具调用成功")


async def main() -> None:
    try:
        env = build_agent_env()
        model = env.get("ANTHROPIC_MODEL")
        base = env.get("ANTHROPIC_BASE_URL", "(官方 API)")
        print(f"agent 端点: model={model} base_url={base}")
    except AgentModelNotConfiguredError as e:
        print(f"✗ {e}")
        print("  请先启动后端在「模型管理」页新增 agent 类型模型并设默认，再重跑本脚本")
        sys.exit(2)

    session_id = await test_basic_run()
    await test_resume(session_id)
    await test_interrupt()
    await test_mcp_tool()
    print("\n✅ 全部通过：agent 运行 / resume / interrupt / 进程内 MCP 工具")


if __name__ == "__main__":
    asyncio.run(main())
