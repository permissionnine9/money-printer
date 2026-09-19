---
name: Claude Agent SDK 封装逻辑
摘要: ClaudeSDKClient 消息流归一为 AgentEvent，支持多轮 resume、interrupt 取消与端点环境注入
tags: AgentSDK, ClaudeSDKClient, AgentEvent, wrapper, 模型端点
---

# Claude Agent SDK 封装逻辑

**最后更新:** 2026-09-19

## 逻辑概述

`backend/core/agent_sdk/wrapper.py` 是所有 agent 生成能力的统一底座：基于 `claude_agent_sdk.ClaudeSDKClient`（进程内 MCP 工具必须用 Client 而非 query()）把 SDK 流式消息归一为 `AgentEvent`（`backend/core/agent_sdk/events.py`），经 `on_event` 回调流出；返回 `AgentRunResult`（text/session_id/structured_output/usage/cost_usd/error/interrupted）。移植自 ../annto-knowledge/backend/lib/claude-agent-sdk-wrapper.ts（TypeScript 版），Python 版差异：query() → ClaudeSDKClient、AbortController → asyncio.Event + client.interrupt()、session_id 从 ResultMessage 捕获（SDK 自动落盘 ~/.claude/projects/）。

模型端点不走 SDK 默认配置，由 `build_agent_env()`（`backend/core/agent_sdk/model_env.py`）从模型管理（`ModelManager().get_default_model("agent")`，表 image_models）读取 Anthropic 协议 base_url/api_key/model_id，注入子进程环境变量 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN(+API_KEY) / ANTHROPIC_MODEL，并设 CLAUDE_AGENT_SDK_CLIENT_APP="money-printer/2.0"；未配置默认 agent 模型抛 `AgentModelNotConfiguredError`。Agent SDK 依赖本机 Claude Code CLI，CLI 通过这些变量寻址端点。

对外两个入口：`run_agent(options, on_event)` 一次性运行（`AgentRunOptions` 全量选项），`run_conversation(...)` 多轮会话一轮（内部管理 agent_session_id 的 resume 与新建）。上层形态：形态 A 直跑 SSE（如构思对话）、形态 B 经 `AgentRunRegistry`（`backend/core/agent_sdk/registry.py`）后台 run + 观流，factory 签名 `(on_event, interrupt_event)` 中的 interrupt_event 即传入 wrapper 的 `options.interrupt`。

## 关键流程

**run_agent 主链路（backend/core/agent_sdk/wrapper.py）**

1. 构造环境 — `env = options.env or build_agent_env()`（未配 agent 模型时在此抛 AgentModelNotConfiguredError）
2. 构造 `ClaudeAgentOptions`：system_prompt、max_turns（默认 `DEFAULT_MAX_TURNS=40`）、`tools = options.tools if not None else []`（默认不授予任何内置工具，含联网；能力只能由 mcp_servers 显式注入，传 `READ_ONLY_TOOLS=["Read","Grep","Glob"]` 可开放工作区文件检索需配合 cwd）、mcp_servers、`permission_mode="bypassPermissions"`、`include_partial_messages=True`（流式增量）、`max_thinking_tokens=DEFAULT_THINKING_TOKENS=6000`、`setting_sources=[]`（隔离模式，禁止子进程加载用户级/项目级设置与插件）、env、resume、cwd；`options.output_format` 非空时赋给 sdk_options.output_format（JSON Schema 结构化输出，当前无业务调用方使用）
3. 提示词透明化 — 发起 LLM 调用前先 emit `prompt` 事件（system_prompt/user_prompt/model=env 的 ANTHROPIC_MODEL），形态 A/B 统一覆盖，含 run_conversation 多轮
4. emit 包装 — run_agent 内部包一层 emit：text_delta/thinking 先累积到 accumulated_text/accumulated_thinking 再透传 on_event（为完整 assistant 消息去重与 result 兜底文本服务）
5. 运行 — `async with client` 进入上下文；`options.interrupt` 非空时 `asyncio.create_task(_watch_interrupt())`（await interrupt.wait() → await client.interrupt()）；`await client.query(options.prompt)` 后 `async for msg in client.receive_messages()` 循环分发
6. 消息分发 — StreamEvent → `_handle_stream_event`；AssistantMessage → `_handle_assistant`（去重补发）；UserMessage → `_handle_user`（tool_result）；ResultMessage → 终态；SystemMessage → pass（init 等系统消息不外发）
7. 终态与退出 — ResultMessage.subtype=="success"：`result.text = msg.result or accumulated_text`（兜底）、session_id、structured_output、usage、`cost_usd = msg.total_cost_usd`，emit `result` 事件（usage 只透出 input_tokens/output_tokens）；非 success：`err = ", ".join(msg.errors) or msg.subtype` 置 result.error 并 emit `error` 事件；随后必须 `break`（Client 模式 receive_messages 不会在 result 后自动结束，可多轮 query）
8. 异常收尾 — `ProcessError/CLIConnectionError` 捕获置 error + emit error 事件；`asyncio.CancelledError` 置 interrupted=True、error="已取消"、emit error 后 re-raise；finally 取消 interrupt_watcher；interrupt 已触发但 result 无 error 时兜底 `interrupted=True`，interrupted 则 `error = error or "已取消"`

**流式增量与去重细节**

1. `_handle_stream_event`（include_partial_messages=True 的 StreamEvent）— content_block_start 且 block.type=="tool_use"：记录 `tool_names[block_id]=name`、`tool_inputs.setdefault(block_id,"")`、`index_to_id[index]=block_id`；content_block_delta：thinking_delta → emit `thinking` 事件、text_delta → emit `text_delta` 事件、input_json_delta → 按 index 映射 block_id 把 partial_json 累积进 tool_inputs（不外发）
2. `_handle_assistant`（完整 assistant 消息）— ThinkingBlock：`block.thinking not in accumulated_thinking` 才补发 thinking；ToolUseBlock：登记 tool_names 并 emit `tool_use`（id/tool/input）；TextBlock：`block.text not in accumulated_text` 才补发 text_delta。去重为子串包含判断，流式已发过的完整内容不重复推送
3. `_handle_user`（user 消息中的 ToolResultBlock）— content 为 str 直接用、为 list 则逐项取 dict 的 "text"（非 dict 转 str）join "\n"、否则空串；`preview = text[:50000] + "..." if len(text) > 50000`，emit `tool_result`（id=tool_use_id、tool 经 tool_names 映射（缺省回落 tool_use_id）、result_preview）

**run_conversation 多轮会话（便捷 API）**

1. 签名 `(message, system_prompt, agent_session_id, tools, max_turns=DEFAULT_MAX_TURNS, on_event, interrupt)`，内部组装 `AgentRunOptions(prompt=message, mcp_servers=tools, resume=agent_session_id, ...)` 复用 run_agent；首轮 agent_session_id 传 None 由 SDK 生成，ResultMessage 捕获 session_id 返回，业务层持久化后下轮传入实现 resume
2. 典型消费方：`backend/core/agents/script_workflow.py` 构思对话（ideation_message/ideation_finalize，max_turns=10），agent_session_id 存于 story_ideation 步骤 result_data，消息副本供前端回放还原

**典型调用方（backend/core/agents/）**

- script_workflow.py：大纲生成/定妆照 prompt run_agent（max_turns=2、无 tools 纯文本输出）；分集设计 run_agent（mcp_servers={"script_design": ...} 进程内 MCP 写侧工具 + tools=READ_ONLY_TOOLS 读侧 + cwd=story_cwd + 轮次按集数估算上下限兜底）
- storyboard.py：分镜大纲 run_agent（tools=READ_ONLY_TOOLS、cwd=story_cwd、max_turns=12，剧本目录内自主检索后输出 JSON）
- cwd 来源：`WorkspaceStore.story_cwd(session_id)`（backend/core/persistence/workspace_store.py）返回剧本 story 根绝对路径；缺省 cwd 时子进程继承后端进程 cwd

## 涉及代码

- `backend/core/agent_sdk/wrapper.py` — run_agent/run_conversation/AgentRunOptions/AgentRunResult/_handle_stream_event/_handle_assistant/_handle_user；常量 DEFAULT_MAX_TURNS=40、DEFAULT_THINKING_TOKENS=6000、READ_ONLY_TOOLS
- `backend/core/agent_sdk/events.py` — `@dataclass AgentEvent`（type：thinking/text_delta/tool_use/tool_result/result/error/prompt）+ to_dict（过滤空字段）/to_sse
- `backend/core/agent_sdk/model_env.py` — build_agent_env（端点变量注入 + 清本机同名变量防优先级混乱）+ AgentModelNotConfiguredError
- `backend/core/agent_sdk/registry.py` — AgentRunRegistry/RunHandle：后台 run 与 SSE 观流解耦；RunCoroFactory 签名 `(on_event, interrupt_event) -> Awaitable[dict]`
- `backend/core/agent_sdk/__init__.py` — 包出口再导出 READ_ONLY_TOOLS/AgentRunOptions/run_agent/run_conversation/build_agent_env 等
- `backend/core/agents/script_workflow.py` — 构思对话 run_conversation、大纲/定妆照 prompt/分集设计 run_agent 调用方
- `backend/core/agents/storyboard.py` — 分镜大纲/素材图/分镜提示词三处 run_agent（均 READ_ONLY_TOOLS + cwd，max_turns 分别 12/8/16）调用方
- `backend/core/persistence/workspace_store.py` — story_cwd：run_agent 的 cwd 来源
- `backend/core/persistence/model_manager.py` — 模型配置表 image_models（model_type='agent'）CRUD 与 get_default_model
- `pyproject.toml` — 依赖 `claude-agent-sdk>=0.2.154`（根目录）

## 相关功能

- SSE 事件流协议逻辑（AgentEvent 的 seq 缓冲回放/断线重连，见 logics/sse-event-stream.md）
- 脚本工作流（构思对话、大纲、分集设计）
- 分镜工作流（分镜大纲等）
- 模型管理（agent 模型端点配置）

## 注意事项

- `permission_mode="bypassPermissions"` + cwd 并非沙箱：bypassPermissions 下 Read/Grep/Glob 技术上可读任意绝对路径，「仅限工作区」由 system prompt 与 MAP.md 边界声明软约束。当前产品为单机单用户 CLI 服务（攻击者=受害者本人）此权衡可接受；若后端暴露网络或多人共用，必须补 deny 规则或 OS 级沙箱（wrapper.py 源码注释明确记录该信任模型）
- 默认 `tools=None → []`：不授予任何内置工具（含联网）；READ_ONLY_TOOLS 需配合 cwd 才有意义
- 去重用子串包含判断（`block.text not in accumulated_text`）：完整文本是流式增量的拼接时命中去重；极端情况下流式与完整文本不一致（如服务端聚合改写）会双发，属已知权衡
- `tool_inputs`（input_json_delta 累积的 partial JSON）当前无任何读取方，仅累积未消费；完整 tool_use input 由 AssistantMessage 的 ToolUseBlock.input 提供
- interrupt 语义为协作式：interrupt_event.set() → client.interrupt() → SDK 以非 success result 或异常收尾 → wrapper 兜底标记 interrupted；CancelledError 场景 emit error("已取消") 后 re-raise 交给上层
- ResultMessage 后必须主动 break 退出 receive_messages 循环，否则挂起（Client 支持多轮 query 不自动结束）
- `usage` 字段：AgentRunResult.usage 为 SDK 完整 usage dict，但 result 事件仅透出 input_tokens/output_tokens 两项
- build_agent_env 抛 AgentModelNotConfiguredError 发生在 run_agent 入口（factory 尚未运行或刚开始），错误提示要求在「模型管理」配置 model_type=agent 的默认模型
- 依赖本机 Claude Code CLI 存在且版本匹配（claude-agent-sdk>=0.2.154）；CLIConnectionError/ProcessError 归一为 error 事件，不抛出到 on_event 消费方之外（run_agent 正常返回带 error 的 AgentRunResult）

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析生成，覆盖 run_agent 主链路/流式去重/run_conversation/模型端点注入 |
