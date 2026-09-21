---
name: model-config-conventions
摘要: 模型配置统一存 SQLite image_models（model_type 分 image/chat/agent，同类型默认互斥）；agent 端点经 build_agent_env 注入子进程 env，image 端点经工厂函数构建；Agent 默认零工具、写侧仅经 MCP 注入，无内置默认与环境变量回退；结构化输出能力已移除（prompt 约束 + 调用方 parse 承担），SDK 流缓冲上限提升至 16MB。
tags: [模型配置, ModelManager, image_models, build_agent_env, claude-agent-sdk, Agent调用, MCP, 生图服务, ImageService, MAX_STREAM_BUFFER_SIZE]
---

# 模型配置与 Agent 调用约定

**类别:** 实现规范
**最后更新:** 2026-09-21

## 原因

项目模型接入由三条实现主轴推导出本规范：**模型配置单一存储源（ModelManager + SQLite image_models）**、**端点专属工厂（agent 子进程 env 注入 / image 服务工厂构建）**、**Agent 最小授权调用（默认零工具、写侧仅经 MCP 注入）**。以下约定均直接来自当前源码实现，不做推测。

### 1. 模型配置存储：ModelManager 与 image_models 表

`backend/core/persistence/model_manager.py`：

- `ModelManager(BaseSQLiteManager)`，存储于 SQLite `data/sessions.db`（`BaseSQLiteManager.__init__` 的 `db_path` 默认 `data/sessions.db`，见 `backend/core/persistence/base.py`）。
- 表 `image_models`：

| 字段 | 约定 |
|------|------|
| id | TEXT 主键，uuid4 |
| name | 名称 |
| api_key | DEFAULT ''（明文存 SQLite，代码中无加密处理） |
| base_url | DEFAULT '' |
| model_id | DEFAULT '' |
| is_default | INTEGER，默认 0 |
| model_type | TEXT，默认 'image'（经 `_add_columns_if_missing` 对旧表迁移补列） |
| created_at / updated_at | 时间戳 |

- `MODEL_TYPES = ('image', 'chat', 'agent')`：create/update 时 `model_type` 不在其中则 `raise ValueError`。
- `get_default_model(model_type='image')`：`SELECT * WHERE is_default=1 AND model_type=? LIMIT 1`；无默认返回 `None`。
- **同类型默认互斥**：`create_model(is_default)` / `update_model(is_default)` / `set_default` 均先 `UPDATE image_models SET is_default=0 WHERE model_type=?` 再置目标为 1 —— 同类型内默认唯一。
- **update_model 幂等保护**：清除同类型默认时排除自身 id（`WHERE model_type=? AND id != ?`）；`rowcount==0` 返回 `None`。

### 2. 模型管理 API（backend/api/v1/models.py）

router 挂载于 `app.include_router(models.router, prefix="/api/v1/models")`（`backend/main.py`）：

| 端点 | 用途 |
|------|------|
| GET /api/v1/models | 列表（可选 model_type 过滤） |
| POST /api/v1/models | 新建 |
| PUT /api/v1/models/{uuid} | 更新 |
| POST /api/v1/models/{uuid}/set-default | 设默认 |
| DELETE /api/v1/models/{uuid} | 删除 |

- 请求 schema `ModelConfigRequest`：name（必填非空）/ api_key / base_url / model_id / is_default / model_type。
- **api_key 明文往返**：`api_key` 为普通明文字段，list/get 响应中的 model dict 经 `_row_to_dict` 原样返回 api_key，无脱敏 —— api_key 会经 API 明文传输并返回给前端。
- API 层校验（`_validate_model_request`）：model_type 不在 MODEL_TYPES 返回 400；image 类型强制 model_id 非空（400）。

### 3. agent 端点：build_agent_env() 子进程 env 注入

`backend/core/agent_sdk/model_env.py` 的 `build_agent_env()`：

- 延迟导入 `ModelManager`，取 `get_default_model('agent')`；无默认则 `raise AgentModelNotConfiguredError`（提示在「模型管理」新增 model_type=agent 并设默认）；缺 `model_id` 同样 raise `AgentModelNotConfiguredError`。
- env 构造规则：

| 步骤 | 约定 |
|------|------|
| 继承 | `env = dict(os.environ)`（继承当前进程） |
| 清除 | 先 pop 本机 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` 四个同名变量，避免优先级混乱 |
| base_url | 去尾部斜杠后非空才注入 `ANTHROPIC_BASE_URL` |
| api_key | 非空时同时注入 `ANTHROPIC_AUTH_TOKEN`（Bearer）与 `ANTHROPIC_API_KEY`（x-api-key）双 key，兼容官方/网关 |
| model | `ANTHROPIC_MODEL=model_id`（必填） |
| 附加 | `CLAUDE_AGENT_SDK_CLIENT_APP='money-printer/2.0'` |

- 边界：`api_key` 为空时不注入任何认证变量（仅要求 model_id 必填），代码不强制 api_key 非空。

### 4. Agent 调用：AgentRunOptions 与 run_agent()（backend/core/agent_sdk/wrapper.py）

- `READ_ONLY_TOOLS = ['Read', 'Grep', 'Glob']`（模块级常量）。代码注释承认（注释非事实采信来源，仅记录代码原文）：cwd 不是沙箱，`bypassPermissions` 下 Read/Grep/Glob 技术上可读任意绝对路径，「仅限工作区」由 system prompt 与 MAP.md 软约束。
- `MAX_STREAM_BUFFER_SIZE = 16*1024*1024`（模块常量，wrapper.py 约 L40）：SDK stream-json 单条消息解析缓冲上限。**动机**：Agent Read 图片时 tool_result 会回显整图 base64，2K/4K 原图会撑爆 SDK 默认 1MB 上限，报 `JSON message exceeded maximum buffer size of 1048576 bytes`；构造 `ClaudeAgentOptions` 时传 `max_buffer_size=MAX_STREAM_BUFFER_SIZE` 规避。
- `AgentRunOptions` dataclass（**output_format 字段已删除**，结构化输出能力整体移除）：

| 字段 | 默认 | 语义 |
|------|------|------|
| prompt | 必填 | 用户 prompt |
| system_prompt | None | 系统 prompt |
| max_turns | DEFAULT_MAX_TURNS=40 | 最大轮次 |
| tools | None | None 时 `ClaudeAgentOptions.tools=[]`，即不授予任何内置工具（含联网）；显式传 `READ_ONLY_TOOLS` 才开放检索 |
| mcp_servers | None | 进程内 MCP server（写侧唯一通道） |
| cwd | None | Agent Read/Grep/Glob 边界锚点；缺省继承后端进程 cwd |
| resume | None | 多轮 session_id |
| interrupt | None | asyncio.Event |
| env | None | None 时调 `build_agent_env()` |

- `run_agent()`：
  - `env = options.env or build_agent_env()`；
  - 构造 `ClaudeAgentOptions(permission_mode='bypassPermissions', include_partial_messages=True, max_thinking_tokens=DEFAULT_THINKING_TOKENS=6000, setting_sources=[]（隔离子进程，不加载用户级/项目级设置与插件）, env=env, resume, cwd, max_buffer_size=MAX_STREAM_BUFFER_SIZE)`；
  - 发 LLM 调用前先 emit `type='prompt'` 事件（含最终 system_prompt / user_prompt / model=env.ANTHROPIC_MODEL），提示词透明化。
- 消息处理：

| 消息/事件 | 处理 |
|------|------|
| StreamEvent | content_block_start（tool_use 登记 id→name/index）；content_block_delta（thinking / text_delta / input_json_delta） |
| AssistantMessage | ThinkingBlock / ToolUseBlock / TextBlock，与流式增量去重 |
| UserMessage | ToolResultBlock → tool_result 事件，preview 截断 50000 字符 |
| ResultMessage | success → text / session_id / usage / cost_usd；否则 error 事件；收到后主动 break（Client 模式可多轮 query，不自动结束）。`structured_output` 读取已随 output_format 能力删除 |
| ProcessError / CLIConnectionError | → error 事件 |
| CancelledError | → interrupted=True |

- `run_conversation()`：便捷 API，内部包装 `run_agent`（`resume=agent_session_id`）管理多轮 resume；**签名已删除 tools（mcp_servers）参数** —— ideation 多轮对话不再支持 MCP 注入。结构化产出改由 **prompt 约束 + 调用方解析**（`AgentStepService.run` 的 parse 回调）承担。
- SDK：claude-agent-sdk（pyproject 约束 `>=0.2.154`，uv.lock 锁定 0.2.154；`ClaudeSDKClient` 驱动本机 Claude Code CLI 子进程）；会话由 SDK 自动落盘 `~/.claude/projects/`。

### 5. 工具授权与写侧机制

- wrapper 自身无写工具；写入能力仅经 `AgentRunOptions.mcp_servers` 由调用方注入进程内 MCP server。当前唯一注册点：`backend/core/agents/script_workflow.py` 中 `create_sdk_mcp_server(name='script_design', version='1.0.0', tools=[...])`，工具清单共 5 个（不变）：
  - `_upsert('character')` / `_upsert('scene')` / `_upsert('clue')` / `_upsert('foreshadow')`：四类实体卡的 upsert 工具；
  - `save_episode`：保存分集设计（含单集重设计约束 —— `single_episode_id` 非空时只允许保存该集；落盘前经 `_validate_episode` 校验），直接调 `self.store`（WorkspaceStore）的 `upsert_episode` 等方法落盘。
- script_workflow.py 现经**注入的 AgentStepService / ImageTaskService 编排**（ScriptWorkflow 构造签名含 `script_manager`），生图任务状态由 ImageTaskService 落 DB、不再在 workflow 内手写。
- 核心素材图（原「定妆照」）生成 prompt 已由英文模板改为**中文**（人物三视图 / 场景全景，130-220 中文字）。

### 6. image 端点：生图服务工厂（backend/core/services/image_service.py）

- `build_image_service_from_model_config(model_config_id=None)` 为唯一生图服务工厂：

| 分支 | 行为 |
|------|------|
| model_config_id 非空 | 走 `ModelManager().get_model(id)`；不存在 raise `ImageModelNotConfiguredError`（'生图模型配置不存在'） |
| model_config_id 为 None | 走 `get_default_model('image')`；无默认 raise（提示在「模型管理」添加生图类型并设默认） |
| 逐项校验 | api_key / base_url / model_id 任一为空均 raise `ImageModelNotConfiguredError` |

- 生图链路无内置默认配置、无环境变量回退。
- `ImageService.__init__`：api_key / base_url / image_model 均来自工厂注入；实例无默认模型时 submit 报 `_NOT_CONFIGURED_MSG`（'生图模型未配置（缺少 API Key / Base URL / 模型 ID）…'），返回 `{'success': False}` 不抛异常。
- 协议：OpenAI 标准图片协议，`Authorization: Bearer {api_key}`：
  - 文生图 `POST {base_url}/images/generations`（JSON：model / prompt / size / n=1 / quality=auto / response_format=b64_json）；
  - 图生图 `POST {base_url}/images/edits`（multipart，image 字段可重复，参考图上限 4 张 `reference_images[:4]`）。
- 尺寸推导 `_get_openai_image_size(video_params)`：size_table 按 aspect_ratio（16:9 / 9:16 / 1:1 / 4:3 / 3:2 / 2:3 / 21:9，未知回退 16:9）× 分辨率档位（720p:0 / 1080p:1 / 2k:2 / 4k:3）映射（档位越界取该比例最后一档），宽高须 16 倍数。
- 重试与容错：`httpx.AsyncClient` timeout=300s；最多 3 次尝试，404/429/500/502/503 且非末次时 sleep `5*(attempt+1)`s 后重试；失败返回 `{'success': False, 'error': f'HTTP {code}: text[:300]'}`；b64_json 响应落盘 `static/images/openai_{uuid8}.png`。
- submit/poll 模式：`submit_image_task` 只提交并缓存同步结果到实例级 `_sync_results[request_id='openai-'+uuid12]`；`poll_i2i_task(request_id)` 命中缓存 pop 返回 image_url，未命中返回失败（timeout / poll_interval 参数未使用，保留签名兼容）。
- 压缩常量：`IMAGE_COMPRESS_MAX_SIZE=1920`、`IMAGE_COMPRESS_QUALITY=85`；参考图经 `load_image_bytes`（backend/core/utils/image_utils.py，本地路径或 http URL，可选压缩）。

### 7. chat 类型模型消费方

`image_models` 支持 `model_type='chat'`，但**当前无运行时消费方**：全库 `get_default_model("chat")` 仅 `backend/config.py` 的 `override_src_config` 一处，用于启动时读取并打印/告警默认 Chat 模型（未配置时 warning「chat 相关功能将不可用」），不参与任何请求链路。未来接入 chat 消费方时须沿用「模型管理默认配置 → 显式工厂/读取函数 → 未配置显式报错」的既有模式。

### 8. 端点约定提炼

- **image 端点**：仅经 `build_image_service_from_model_config` ← ModelManager image 默认（或指定 model_config_id），无内置默认 / 无 .env 回退，未配置显式报错。
- **agent 端点**：仅经 `build_agent_env` ← ModelManager agent 默认，注入子进程 env，缺配置抛 `AgentModelNotConfiguredError`，并清除本机同名 ANTHROPIC_* 变量防泄漏 / 优先级混乱。
- 代码中未发现任何硬编码 api_key / base_url / model_id（OSS / ComfyUI 常量属其他服务，与模型端点无关）。

## 适用范围

- `backend/core/persistence/model_manager.py`（模型配置存储）、`backend/api/v1/models.py`（模型管理 API）
- `backend/core/agent_sdk/model_env.py`、`backend/core/agent_sdk/wrapper.py`（agent 端点与 Agent 调用）
- `backend/core/agents/script_workflow.py`（script_design MCP 写侧工具注册）
- `backend/core/services/image_service.py`（image 端点）
- 所有新增模型消费方（新增 agent 步骤、新生图链路、未来 chat 消费方）

## 示例

✅ **正确做法:**

1. 新增 agent 调用不传 `env`，让 `run_agent()` 自动走 `build_agent_env()`；缺 agent 默认模型时让 `AgentModelNotConfiguredError` 显式抛出提示用户配置，而非绕过工厂自拼 env。
2. Agent 默认零工具（`tools=None` → `ClaudeAgentOptions.tools=[]`）；需要检索时显式 `tools=READ_ONLY_TOOLS` 并配合 `cwd=` 锁定 story 工作区作为边界锚点。
3. 写侧一律经 `AgentRunOptions.mcp_servers` 注入进程内 MCP server（script_design：upsert character/scene/clue/foreshadow + save_episode → WorkspaceStore），不给 agent 授予文件写工具。
4. 生图只经 `build_image_service_from_model_config(model_config_id)` 工厂构建 ImageService，不在生图链路里内置默认配置或加环境变量回退。
5. 设默认模型走 `create_model(is_default)` / `update_model(is_default)` / `set_default`，依赖其同类型默认互斥逻辑（先清同类型再置目标）。
6. 更新已有默认模型配置时依赖 `update_model` 的幂等保护（清除同类型默认时排除自身 id，`WHERE model_type=? AND id != ?`）。
7. 多轮对话用 `run_conversation()`（内部包装 run_agent：`resume=agent_session_id`）管理 resume；**不传 tools/mcp_servers**（签名已无该参数）。需要结构化产出时在 prompt 中约定输出格式，由调用方解析（如 `AgentStepService.run` 的 parse 回调）。

❌ **错误做法:**

1. 在代码中硬编码 api_key / base_url / model_id，或给生图/agent 链路加内置默认配置、.env 回退 —— 项目约定是未配置显式报错。
2. 假定 Agent 调用默认有工具或联网可用 —— `tools=None` 即 `tools=[]`，不授予任何内置工具。
3. 给 agent 直接授予写类内置工具 —— 写侧唯一通道是 `mcp_servers` 注入的进程内 MCP 工具。
4. 在 `build_agent_env()` 之外自行向子进程 env 塞 ANTHROPIC_* 变量 —— 工厂会先 pop 本机同名四个变量，绕过工厂会引入优先级混乱 / 本机凭证混入。
5. 依赖 `cwd` 做安全沙箱 —— 代码注释承认 cwd 不是沙箱，`bypassPermissions` 下 Read/Grep/Glob 技术上可读任意绝对路径，「仅限工作区」由 system prompt 与 MAP.md 软约束。
6. 依赖生图 submit/poll 的 timeout / poll_interval 参数做异步等待 —— 参数未使用，实际是同步结果缓存在 `_sync_results`。
7. 假定 chat 类型默认模型已有运行时消费方 —— 当前全库唯一读取点是 backend/config.py 启动日志（override_src_config），请求链路中无人消费。
8. create/update 模型时使用 MODEL_TYPES 之外的 model_type —— 会 `raise ValueError`（API 层同样返回 400）。
9. 期望 `AgentRunResult.structured_output` —— **已删除**（AgentRunOptions.output_format 与 msg.structured_output 读取均已移除），结构化产出改由 prompt 约束 + 调用方 parse 回调承担。
10. 向 `run_conversation()` 传 tools/mcp_servers —— 签名已删除该参数，ideation 多轮对话不支持 MCP 注入。

## 待补充

| 事项 | 说明 |
|------|------|
| （暂无） | 初版自校时已核实的三处待补充项（script_design 工具清单 / chat 消费方 / models API schema）均已回源码确认并写入正文 |

## 迭代记录

| 日期 | 记录 |
|------|------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修正：删除不存在的 llm_service.pyc 引用（第 7 节改为「chat 默认模型仅 config.py 启动日志读取，无运行时消费方」）；补全 models API schema（api_key 明文往返、image 类型 model_id 必填）；补全 script_design MCP 工具清单（upsert×4 + save_episode）；SDK 版本表述精确为 pyproject >=0.2.154 / uv.lock 锁定 0.2.154 |
| 2026-09-21 | 迭代修订 — 删除 output_format 相关事实（AgentRunOptions.output_format、AgentRunResult.structured_output、ClaudeAgentOptions.output_format 注入与 ResultMessage structured_output 读取）；run_conversation 签名删除 tools（mcp_servers）参数；新增 wrapper 模块常量 MAX_STREAM_BUFFER_SIZE=16MB（Agent Read 图片时 tool_result 回显整图 base64 撑爆 SDK 默认 1MB，构造 ClaudeAgentOptions 传 max_buffer_size）；第 5 节补 script_workflow 经注入的 AgentStepService/ImageTaskService 编排（构造含 script_manager）、核心素材图 prompt 改中文（人物三视图/场景全景，130-220 中文字）；示例与错误做法同步修订 |
