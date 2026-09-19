---
name: Agent 模型端点环境注入逻辑
摘要: build_agent_env 从 SQLite image_models 读 agent 默认模型，构造子进程环境（ANTHROPIC_* 四变量双认证注入）驱动 Claude Code CLI
tags: 模型环境注入, build_agent_env, ANTHROPIC_BASE_URL, ClaudeSDKClient, image_models, ModelManager, AgentModelNotConfiguredError
---

# Agent 模型端点环境注入逻辑

**最后更新:** 2026-09-19

## 逻辑概述

Claude Agent SDK 不走进程内的 HTTP 客户端，而是以**子进程**方式拉起本机 Claude Code CLI，CLI 通过一组 `ANTHROPIC_*` 环境变量寻址端点。`build_agent_env()`（`backend/core/agent_sdk/model_env.py`）就是这组变量的唯一构造器：从 SQLite `image_models` 表读取 `model_type='agent'` 的默认模型（Anthropic 协议 base_url/api_key/model_id），在继承当前进程环境的基础上注入端点变量，交给 `ClaudeAgentOptions(env=...)`。

配置权威源是数据库而非 `backend/.env`：模型端点经「模型管理」页（`/api/v1/models`）运行时维护，`backend/.env` 只承载 ComfyUI/OSS 等非 LLM 端点。这样 agent 端点可以不改代码/不重启换模型，且 api_key 只存 SQLite（与 `.env` 同属勿提交敏感面）。

注入规则（按源码顺序）：

1. 继承 — `env = dict(os.environ)`，子进程沿用后端进程其余变量（PATH 等）
2. 清场 — 先 `pop` 本机可能存在的 4 个同名变量（`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL`），避免开发者本机配置与库内配置优先级混乱
3. `ANTHROPIC_BASE_URL` — base_url 非空才注入（strip + `rstrip("/")` 去尾斜杠）；为空 = 官方 API，不设变量
4. 双认证 — api_key 非空时**同一 key 同时注入** `ANTHROPIC_AUTH_TOKEN`（Bearer，网关常用）与 `ANTHROPIC_API_KEY`（x-api-key，官方协议），一份配置兼容官方 API 与各类网关
5. `ANTHROPIC_MODEL` — model_id 为空直接抛 `AgentModelNotConfiguredError`（agent 无"隐式默认模型"可言），非空注入
6. `CLAUDE_AGENT_SDK_CLIENT_APP = "money-printer/2.0"` — 标记调用方应用，供端点侧识别流量来源

未配置默认 agent 模型同样抛 `AgentModelNotConfiguredError`，报错文案直接引导用户去「模型管理」新增 `model_type=agent` 模型并设默认。该异常在业务层无专门捕获（grep 全 backend/ 仅 `agent_sdk/__init__.py` 导出与手动测试引用），从 `run_agent` 调用点向 API 层冒泡按通用异常处理。

配套隔离：`ClaudeAgentOptions(setting_sources=[])`（`backend/core/agent_sdk/wrapper.py`）禁止子进程加载任何用户级/项目级 Claude 设置与插件，保证只有本函数注入的端点变量生效。

## 关键流程

**build_agent_env（环境构造）**

1. 延迟导入 `ModelManager`（函数体内 import，避免持久层初始化顺序耦合）
2. `ModelManager().get_default_model("agent")` — `SELECT * FROM image_models WHERE is_default = 1 AND model_type = ? LIMIT 1`，无默认行返回 None → 抛 `AgentModelNotConfiguredError`
3. 按上节 1-6 规则构造并返回完整环境 dict（注意：api_key 允许为空——如本地网关免鉴权场景，此时仅跳过双认证注入）

**消费点（run_agent 接线）**

1. `backend/core/agent_sdk/wrapper.py` 的 `run_agent`：`env = options.env or build_agent_env()` — `AgentRunOptions.env` 显式传入可整体覆盖；当前业务调用方（script_workflow.py、storyboard.py）均不传 env，全部走默认注入
2. env 传入 `ClaudeAgentOptions(env=env, ...)` → `ClaudeSDKClient` 子进程（本机 Claude Code CLI）继承该环境
3. 副产物：发起 LLM 调用前流出 `AgentEvent(type="prompt")`，其 `model` 字段取 `env.get("ANTHROPIC_MODEL", "")` —— 提示词透明化事件同时携带实际生效模型名
4. `run_conversation`（多轮会话便捷入口）内部转调 `run_agent`，同享注入

**配置维护链（image_models 表）**

1. 表结构（`backend/core/persistence/model_manager.py` `_create_schema`）：id/name/api_key/base_url/model_id/is_default/model_type/created_at/updated_at，存 `data/sessions.db`
2. `MODEL_TYPES = ("image", "chat", "agent")`，每类默认互斥 — `create_model`/`update_model`/`set_default` 均先 `UPDATE ... SET is_default = 0 WHERE model_type = ?` 清同类型默认再置新默认
3. REST 入口 `/api/v1/models`（`backend/api/v1/models.py`）：GET 列表（可按 model_type 过滤）/ POST 新增 / PUT 更新 / `POST /{id}/set-default` / DELETE；model_type 越界 400
4. 前端维护页 `frontend/src/pages/ModelsPage.tsx`：agent 类型紫色 Tag 标「Agent」，类型筛选项「Agent 模型」

**prompt 事件到前端展示**

1. 前端 `frontend/src/components/script/AgentRunProgress.tsx` 订阅 SSE prompt 事件，缓存 `{systemPrompt, userPrompt, model}`
2. `frontend/src/components/common/PromptViewerModal.tsx` 弹窗展示三者 —— model 名即本逻辑注入的 `ANTHROPIC_MODEL`，用户可在 UI 直接确认当前 agent 跑在哪个模型上

## 涉及代码

- `backend/core/agent_sdk/model_env.py` — 核心：`build_agent_env()`（继承+清场+四变量注入）、`AgentModelNotConfiguredError`
- `backend/core/agent_sdk/wrapper.py` — 消费：`run_agent` 的 `options.env or build_agent_env()`、`ClaudeAgentOptions(env=...)` + `setting_sources=[]` 隔离、prompt 事件 model 字段；`AgentRunOptions.env` 覆盖口
- `backend/core/agent_sdk/__init__.py` — 集成层导出（build_agent_env / AgentModelNotConfiguredError 随包暴露）
- `backend/core/persistence/model_manager.py` — `ModelManager`：`get_default_model`、默认互斥逻辑、`image_models` 表 DDL、`MODEL_TYPES`
- `backend/api/v1/models.py` — `/api/v1/models` 模型管理 CRUD + set-default
- `backend/deps.py` — `get_model_manager()`（API 层 ModelManager 注入源）
- `backend/core/agents/script_workflow.py` — 剧本工作流调用方（run_conversation ×2 + run_agent ×3，均不传 env 走默认注入）
- `backend/core/agents/storyboard.py` — 视频侧分镜调用方（run_agent ×3，同上）
- `tests/manual/test_agent_sdk.py` — 手动联调脚本：main() 先 `build_agent_env()` 自检端点，未配置 `AgentModelNotConfiguredError` 时提示去模型管理页配置并 `sys.exit(2)`
- `frontend/src/pages/ModelsPage.tsx` — 模型管理页（agent 类型维护入口）
- `frontend/src/components/script/AgentRunProgress.tsx` / `frontend/src/components/common/PromptViewerModal.tsx` — prompt 事件 model 名展示

## 相关功能

- 模型管理页（ModelsPage：image/chat/agent 三类端点 CRUD 与默认互斥）
- Claude Agent SDK 封装（wrapper：子进程生命周期、事件归一、resume/interrupt，见 agent-sdk-wrapper.md）
- 剧本 4 步工作流 / 视频 V2 工作流（所有 agent 步骤的端点寻址都依赖本逻辑）
- 提示词透明化（prompt 事件 → PromptViewerModal，model 字段来源于此）
