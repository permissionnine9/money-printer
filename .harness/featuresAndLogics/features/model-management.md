---
name: 模型配置管理
摘要: 通过前端 /models 页面与后端 /api/v1/models 接口集中管理 image/chat/agent 三类模型配置（增删改查、同类型互斥默认），生成链路各服务按类型读取默认模型。
tags: 模型配置, 后端API, 前端页面, SQLite
---

# 模型配置管理

**状态:** 已完成
**最后更新:** 2026-09-19

## 功能概述

集中管理三类模型配置（`image` 生图 / `chat` 对话 / `agent` 智能体），每条配置包含名称、API Key、Base URL、模型 ID 与默认标记，三类各自维护唯一默认模型。页面文案（代码内 UI 文案）：三类各自独立默认；默认生图模型用于素材图/首尾帧生成；默认 Chat 模型用于脚本优化、思维导图、分片等 LLM 环节；默认 Agent 模型用于剧本创作各步骤的 Agent 调用。

前端为路由 `/models`（App.tsx:19 注册）的 `ModelsPage`，基于 antd Card+Table+Modal+Form 实现；后端为挂载于 `/api/v1/models` 的 REST CRUD（backend/main.py:81 `include_router(models.router, prefix="/api/v1/models")`），持久化到 SQLite `image_models` 表。

整体数据流：前端 ModelsPage → modelApi（axios，`/api/v1`）→ backend/api/v1/models.py → Depends(get_model_manager) → ModelManager（SQLite image_models 表）；生成链路各服务只读取对应类型默认模型。

## 核心代码路径

- `backend/api/v1/models.py` — API 层：`/api/v1/models` 下 5 条路由（列表/创建/更新/设默认/删除），共用校验 `_validate_model_request`，负责 400/404/500 错误映射
- `frontend/src/pages/ModelsPage.tsx` — 前端页面：Segmented 类型筛选、配置表格（脱敏 API Key）、新增/编辑共用 Modal、设为默认与删除操作
- `frontend/src/api/client.ts` — 前端 API client：`modelApi`（第 240 行起），提供 list/create/update/setDefault/remove 五个方法，axios baseURL `/api/v1`
- `backend/core/persistence/model_manager.py` — 持久层：`ModelManager(BaseSQLiteManager)`，`image_models` 表 CRUD 与同类型互斥默认逻辑，模块级常量 `MODEL_TYPES`
- `backend/deps.py` — 依赖注入：`get_model_manager()`（第 45-46 行，`@lru_cache` 装饰的单例；注释称与 SessionManager 共用同一 SQLite `data/sessions.db`，已证实）

## 关键逻辑说明

### 后端 API 层（backend/api/v1/models.py，挂载前缀 /api/v1/models）

| 路由 | 处理函数 | 行为 |
|------|---------|------|
| GET /models?model_type= | list_models | 可选按类型过滤；非法 model_type 返回 400（`model_type 仅支持 ...`）；返回 `{success, models}` |
| POST /models | create_model | 校验通过返回 `{success, message:'模型配置已创建', model}`；ValueError → 400 |
| PUT /models/{model_uuid} | update_model | 返回 `{success, message:'模型配置已更新', model}`；不存在 → 404（`模型配置不存在`） |
| POST /models/{model_uuid}/set-default | set_default_model | 不存在 → 404 同上；成功消息 `已将「{name}」设为默认{label}模型`，label 按类型映射：image→生图、chat→chat、agent→agent |
| DELETE /models/{model_uuid} | delete_model | 先 get_model 判存在（无 → 404）；删除失败 → 500；成功 `{success, message:'模型配置已删除'}` |

请求模型 `ModelConfigRequest` 字段：`name`(必填)、`api_key`(默认 '')、`base_url`(默认 '')、`model_id`(默认 '')、`is_default`(默认 False)、`model_type`(默认 'image')。共用校验 `_validate_model_request`：name 非空（strip 后）、`model_type ∈ MODEL_TYPES`、image 类型时 model_id 不能为空；所有字符串字段 strip 后落库。

### 持久层（backend/core/persistence/model_manager.py）

- `MODEL_TYPES = ('image', 'chat', 'agent')` 模块级常量。
- 表 `image_models`（历史命名，三类模型共用此表）：`id TEXT PRIMARY KEY`(uuid)、`name TEXT NOT NULL`、`api_key TEXT NOT NULL DEFAULT ''`、`base_url TEXT NOT NULL DEFAULT ''`、`model_id TEXT NOT NULL DEFAULT ''`、`is_default INTEGER NOT NULL DEFAULT 0`、`created_at TEXT NOT NULL`、`updated_at TEXT NOT NULL`；旧表迁移经 `_add_columns_if_missing` 增加 `model_type TEXT NOT NULL DEFAULT 'image'` 列。
- `_row_to_dict`：is_default 转 bool，model_type 缺省回退 'image'。
- `list_models(model_type=None)`：有过滤按 `model_type = ?`，排序 is_default DESC, created_at ASC；无过滤排序 model_type ASC, is_default DESC, created_at ASC（默认的排前面）。
- `get_model(model_id)`：按 id 查单条，无则 None。
- `get_default_model(model_type='image')`：`WHERE is_default=1 AND model_type=? LIMIT 1`，无默认返回 None。
- `create_model`：model_type 不在 MODEL_TYPES 抛 ValueError；生成 uuid4 主键；若 is_default=True 先 UPDATE 同 model_type 全部置 is_default=0 再 INSERT（同类型互斥默认）。
- `update_model(model_id, name, api_key, base_url, model_id_field, is_default, model_type)`：非法类型 ValueError；is_default=True 时先清同 model_type 其他默认（`AND id != 本条`）；UPDATE rowcount==0 返回 None（API 层转 404）。
- `set_default(model_id)`：先查存在性（None 则 404）；事务内先 UPDATE 同 model_type 全部 is_default=0，再 UPDATE 本条 is_default=1 + updated_at。
- `delete_model(model_id)`：DELETE BY id，返回 bool。
- 所有字段（api_key/base_url/model_id）在 API 层 strip 后明文写入 SQLite（data/sessions.db，BaseSQLiteManager 默认路径），无加密。
- **存储共库确认**：`BaseSQLiteManager.__init__`（backend/core/persistence/base.py:25）与 `SessionManager.__init__`（session_manager.py:42）默认 db_path 均为 `data/sessions.db`，ModelManager 与两个 SessionManager、ScriptManager 确实共用同一 db 文件；`_init_database` 开启 WAL（PRAGMA journal_mode=WAL）支撑多 manager 并发读写。

### 前端页面（frontend/src/pages/ModelsPage.tsx）

- 列表筛选：Segmented 筛选 all/image/chat/agent（filterType state），切换后 `setTimeout(0)` 内调 `modelApi.list` 重新拉取；useEffect 初次 `loadModels`。
- 表格列：
  - 名称：含类型 Tag（chat=geekblue `Chat`、agent=purple `Agent`、image=cyan `生图`），is_default 再加绿色 `默认` Tag
  - Base URL、模型 ID
  - API Key：脱敏显示 `slice(0,6)+'****'+slice(-4)`，空显示 `（未填写，回退环境变量）`
  - 操作：非默认记录显示 `设为默认` 按钮 + 编辑 + Popconfirm 删除
- 新增/编辑共用 Modal，Form 字段：`model_type`(Segmented)、`name`(必填)、`api_key`(必填 Input.Password)、`base_url`(必填)、`model_id`(非必填)、`is_default`(Switch，valuePropName='checked')；`openCreate` 默认 model_type 取当前筛选（all 时为 image）、is_default=false。
- `handleSave`：`form.validateFields` → editing ? `modelApi.update(id, payload)` : `modelApi.create(payload)`，成功 message.success + 关弹窗 + loadModels；errorFields 异常静默返回（表单校验错误）。
- `modelApi`（frontend/src/api/client.ts:240）：`list(modelType?)` → GET /models?model_type=、`create` → POST /models、`update(id,payload)` → PUT /models/{id}、`setDefault(id)` → POST /models/{id}/set-default、`remove(id)` → DELETE /models/{id}；axios baseURL `/api/v1`。
- TS 类型 `ImageModelConfig`（frontend/src/types/index.ts:234）：id, name, api_key, base_url, model_id, is_default, model_type: 'image'|'chat'|'agent', created_at, updated_at。
- 前端不持久化任何密钥（无 localStorage），api_key 仅经请求体传给后端并渲染脱敏值。

### 依赖注入与消费方

- `backend/deps.py:45-46 get_model_manager()`：`@lru_cache` 装饰的单例，`return ModelManager()`；与 SessionManager 共用同一 SQLite data/sessions.db（已证实，见上文存储共库确认）。
- 默认模型消费方（grep get_default_model 证实）：
  - `backend/config.py:21-22` — `override_src_config` 启动时读 image/chat 默认模型并打印日志（未配置时 warning 提示去「模型管理」配置）
  - `backend/core/agent_sdk/model_env.py:28` — `build_agent_env`：`ModelManager().get_default_model('agent')` 构造 agent 子进程环境：先清除本机同名 `ANTHROPIC_BASE_URL/AUTH_TOKEN/API_KEY/MODEL` 变量，再注入 ANTHROPIC_BASE_URL、ANTHROPIC_AUTH_TOKEN+ANTHROPIC_API_KEY（双注入，兼容官方 API 与网关）、ANTHROPIC_MODEL 与 `CLAUDE_AGENT_SDK_CLIENT_APP='money-printer/2.0'`；未配置或缺 model_id 抛 AgentModelNotConfiguredError
  - `backend/core/services/image_service.py:45` — `build_image_service_from_model_config`（唯一生图服务工厂）：传入 model_config_id 时按 `get_model(id)` 精确选模型（不存在抛 ImageModelNotConfiguredError），否则 `get_default_model('image')`；随后 api_key/base_url/model_id 任一为空均显式报错（无内置默认）
  - `backend/api/v1/script_sessions.py:412` — `_require_default_image_model`：定妆照生成等生图路由前置校验，未指定 model_config_id 且无默认 image 模型时直接 400

## 依赖与复用关系

- 依赖: FastAPI Depends（backend/deps.py 的 get_model_manager 依赖注入）；BaseSQLiteManager（SQLite 持久化基类，默认路径 data/sessions.db，WAL 模式）；前端 antd 组件库（Card/Table/Modal/Form/Segmented/Tag/Switch/Popconfirm）、axios（frontend/src/api/client.ts，baseURL /api/v1）、@/types 的 ImageModelConfig
- 被依赖: backend/config.py（启动读取打印 image/chat 默认模型）、backend/core/agent_sdk/model_env.py（agent 默认模型 → 子进程环境变量）、backend/core/services/image_service.py（image 默认模型/指定配置 → 生图服务）、backend/api/v1/script_sessions.py（定妆照生图前校验 image 默认模型）
- 可复用组件: BaseSQLiteManager（连接/建表迁移/时间戳/JSON 列样板，SessionManager/ScriptManager/ModelManager 三 manager 共用）；`modelApi`（前端模型 CRUD client，可被其他需要模型配置的页面复用）

## 注意事项

- **api_key 明文存储**：image_models 表未做加密，api_key 以明文 TEXT 存 SQLite（data/sessions.db），代码无加密逻辑（安全属性如实描述为明文存储）。
- **前后端校验强度不一致**：前端表单将 api_key/base_url 设为必填，而后端 API 对二者无非空校验（后端仅要求 name 与 image 类型的 model_id）。
- **model_type 可被修改**：update_model 允许修改 model_type 字段本身（可把记录从 image 改为 chat）；前端编辑弹窗允许改 Segmented model_type。行为（依代码确定）：is_default=True 时按「新类型」清理其他默认；若本条未设默认且改了类型，旧类型默认态随记录迁走而消失，代码无自动补选新默认的逻辑。
- **chat 默认模型消费方有限**：当前源码中 `get_default_model('chat')` 消费仅 backend/config.py:22 一处（启动读取打印）；llm_service.py 源码文件已不存在（仅残留 `__pycache__/llm_service.cpython-313.pyc` 编译产物），源码级无其他 chat 模型消费方。
- **同类型互斥默认**：create/update/set_default 均先清同 model_type 其他默认再设置本条；`get_default_model` 取 LIMIT 1，每类至多一条默认。
- **UUID 主键**：主键为 uuid4 生成的字符串（非自增），API 路径参数为 `{model_uuid}`。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修正：get_model_manager 更正为 @lru_cache 单例（源码 deps.py:45-46）；消解 4 处「待补充」— base.py 证实 ModelManager 与 SessionManager 共用 data/sessions.db（WAL）、image_service 工厂双路径逻辑已逐行核对、llm_service.py 源码已不存在（仅 .pyc 残留）、update 改类型默认态行为按代码确定；补充 model_env 清变量/双注入细节与 ImageModelConfig 的 created_at/updated_at 字段 |
