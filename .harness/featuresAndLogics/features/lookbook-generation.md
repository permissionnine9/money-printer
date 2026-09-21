---
name: 剧本核心素材图生成
摘要: 剧本工作流第 4 步（lookbook_images）：Agent 单轮产出中文生图 prompt 后走 ImageTaskService 确定性生图状态机（间隔提交+并发轮询），为人物（三视图）/场景（全景）实体生成核心素材图（原「定妆照」），支持单张重生成/删除/素材库导入与手动完成步骤。
tags: 剧本工作流, 核心素材图, 素材库, 生图, AgentSDK, SQLite, 前端组件
---

# 剧本核心素材图生成（原「定妆照」）

**状态:** 已完成
**最后更新:** 2026-09-21

## 功能概述

剧本创作工作流（4 步）的第 4 步 `lookbook_images`：为分集设计中注册的人物（character）/场景（scene）实体生成"核心素材图"（原「定妆照」概念改名，全剧统一的视觉锚点图）。设计为「Agent 出 prompt + 确定性生图」两段式——先用 Agent SDK 单轮调用把实体设定翻译成**中文**生图 prompt（130-220 中文字，用户可直接读懂并修改；结合剧本故事逻辑确定统一视觉风格），再经 ImageTaskService 按状态机逐张提交生图任务并轮询回写。

关键特征：

- **实体类型限制**：仅 `character`/`scene` 可生成素材图，线索（clue）/伏笔（foreshadow）无视觉形象被拒绝。
- **双存储**：生图任务状态机在 SQLite `lookbook_images` 表（权威源），生成成功后把 `lookbook_image_id`/`lookbook_image_path` 引用回写到工作区实体文件 frontmatter（文件只存引用，任务本体在 DB）。
- **手动完成**：本步骤无自然终点（按需生成），由用户点「完成本步骤」手动标记步骤完成。
- **统一生图参数**：`LOOKBOOK_VIDEO_PARAMS = VideoParams(resolution="1080p", aspect_ratio="16:9")`，全剧统一。
- **素材库（新）**：跨剧本复用已完成素材图（复制导入，详见 lookbook-library feature 文档）。

整体数据流：前端 StepLookbook 卡片弹窗 → scriptStepApi（axios `/api/v1`）→ backend/api/v1/script_sessions.py 素材图路由 → run_agent_endpoint（deps.py → AgentRunRegistry，返回 run_id，超并发则排队）→ ScriptWorkflow.generate_lookbook / regenerate_lookbook_image → Agent 出 prompt（lookbook_prompts.md 模板）→ ImageTaskService（统一状态机：submit_image_task + poll_i2i_task）→ ScriptManager 更新 lookbook_images 表 → WorkspaceStore.set_entity_lookbook 回写实体文件 → 前端 2s 轮询刷新。

## 核心代码路径

- `backend/api/v1/script_sessions.py` — API 层：7 条素材图路由（generate/complete/list/regenerate/delete + 新增 library/import），生图路由前置校验 `_require_default_image_model`
- `backend/core/agents/script_workflow.py` — 工作流核心：`generate_lookbook`/`regenerate_lookbook_image`/`complete_lookbook`；构造注入 ImageTaskService（`image_tasks`）；模块常量 `LOOKBOOK_VIDEO_PARAMS`
- `backend/core/services/image_task_service.py` — **生图任务状态机统一服务**（ImageTaskSpec + ImageTaskService）：insert(pending)→submit→processing→poll→completed/failed；run_batch（IMAGE_REQUEST_TIME_GAP 间隔限流 + gather 并发轮询，单张失败标 failed 不中断）/run_single（失败标 failed 并抛 WorkflowError）；依赖注入 image_service 参数 + update_row 回调适配 lookbook/mat_* 两类表 + on_completed 归档钩子
- `backend/prompts/lookbook_prompts.md` — Agent prompt 模板：AI 视觉导演两步法（定风格 → 按实体类型写中文 prompt），输出严格 JSON 数组
- `backend/core/agents/system_prompts.py` — `LOOKBOOK_PROMPTS_SYSTEM`：严格 JSON 输出约束的 system prompt
- `backend/core/persistence/script_manager.py` — 持久层：`lookbook_images` 表与 insert（新增 image_path/meta 参数）/update/get/list/delete；`list_completed_lookbooks`（全局 completed 且 image_path 非空）；`delete_script_data(keep_completed_lookbooks)`
- `backend/core/persistence/workspace_store.py` — `set_entity_lookbook`：实体文件 frontmatter 回写素材图引用
- `backend/core/services/lookbook_library_service.py` — 素材库服务：`list_lookbook_library`/`import_lookbook_from_library`（复制导入+回滚）
- `backend/core/services/image_service.py` — 生图服务：`build_image_service_from_model_config`/`submit_image_task`/`poll_i2i_task`
- `frontend/src/components/script/StepLookbook.tsx` — 前端步骤组件：人物/场景分组卡片、生成/重生成弹窗、「从素材库选择」、2s 轮询、完成本步骤
- `frontend/src/components/script/LookbookLibraryModal.tsx` — 素材库弹窗（分组展示/单选绑定）
- `frontend/src/api/client.ts` — scriptStepApi 素材图方法（含 getLookbookLibrary/importLookbookImage）
- `frontend/src/types/index.ts` — `LookbookImage` 与 `LookbookLibraryItem`/`LookbookLibraryGroup` TS 类型
- `tests/manual/test_lookbook_library.py` — 218 行回归（保留语义/跨会话过滤/HTTP 层）

## 关键逻辑说明

### API 层（backend/api/v1/script_sessions.py，前缀 /api/v1/script-sessions）

| 路由 | 处理函数 | 行为 |
|------|---------|------|
| POST /{session_id}/lookbook/generate | generate_lookbook | 生图模型前置校验 → `run_agent_endpoint("lookbook_images", factory)` 返回 `{run_id}`（超并发上限 5 则排队） |
| POST /{session_id}/lookbook/complete | complete_lookbook | 调 workflow.complete_lookbook 手动标记完成，返回 `{completed: True}` |
| GET /{session_id}/lookbook?entity_id=&task_status= | list_lookbook | 按会话（可加实体/状态过滤）列素材图，`{images, total}` |
| GET /{session_id}/lookbook/library | get_lookbook_library | 素材库：跨剧本已完成素材分组查询，`{groups, total}`（当前会话组 key="current" 排第一） |
| POST /{session_id}/lookbook/import | import_lookbook | 素材库导入：`LookbookImportRequest{entity_id, source_image_id}` → 复制源行为新 completed 行（meta 记 imported_from）+ 回写实体锚点，失败回滚 |
| POST /{session_id}/lookbook/{image_id}/regenerate | regenerate_lookbook_image | 单张重生成 → `run_agent_endpoint(f"lookbook_regen_{image_id}")` |
| DELETE /{session_id}/lookbook/{image_id} | delete_lookbook_image | ScriptManager.delete_lookbook，消息 `素材图已删除`/`素材图不存在` |

- `_require_default_image_model(model_config_id)`：请求未指定 model_config_id 且「模型管理」无默认 image 模型时直接 400（`未配置默认生图模型：请在「模型管理」...`），避免等到 run 流里才报错。
- 请求 schema（backend/schemas/script.py）：`LookbookGenerateRequest{entity_ids: list[str] (min_length=1), style_prompt: str = "", model_config_id: Optional[str]}`；`LookbookRegenerateRequest{prompt: Optional[str], model_config_id: Optional[str]}`；`LookbookImportRequest{entity_id: pattern 校验, source_image_id: min_length=1}`。
- `run_agent_endpoint`（backend/deps.py，原 start_agent_run 改名）统一提交到 `get_run_registry()` 并返回 `{"success": True, "data": {"run_id": ...}}`。

### 生成主流程（ScriptWorkflow.generate_lookbook）

1. **前置校验**：`require_step_data(session_id, "episode_design")`（第 3 步未完成抛业务异常）；entity_ids 非空；勾选实体必须属于本会话（`store.list_entities` 对账，缺失抛 `实体不存在或不属于本会话`）；类型必须为 character/scene（否则抛 `仅人物/场景可生成定妆照，线索/伏笔不支持`）。
2. **Agent 出 prompt**：`load_story_logic(session_id)[:1500]`（workspace_sections 服务，工作区文件优先，DB 老数据 fallback）；`self.prompts.render("lookbook_prompts", {story_logic, style_prompt, entities})` 渲染模板；经注入的 AgentStepService 单轮调用（LOOKBOOK_PROMPTS_SYSTEM，max_turns=2）；`extract_json_array(result.text)` 解析 JSON 数组。
3. **缺漏兜底**：以勾选集为准，Agent 漏掉的实体用兜底 prompt（「名称+设定」）。
4. **确定性生图（ImageTaskService.run_batch 统一状态机）**：
   - `build_image_service_from_model_config(model_config_id)` 构造 ImageService（None=默认生图模型；无配置/缺 API Key/缺 Base URL 抛 ImageModelNotConfiguredError）。
   - 每实体先 `insert_lookbook` 落库（image_id 为 `lb_` + uuid hex 前 10 位，初始 pending）。
   - `run_batch`：逐张 `submit_image_task(prompt, LOOKBOOK_VIDEO_PARAMS, None)`，两张之间 `await asyncio.sleep(IMAGE_REQUEST_TIME_GAP)`（12 秒，防生图服务限流）；提交成功 → `{task_id, task_status: processing}`，失败/异常 → task_status=failed；interrupt 置位抛 `已取消`。
   - `asyncio.gather` 并发 `poll_i2i_task(request_id, timeout=180, poll_interval=5)`（注：OpenAI 协议下 submit 时已同步生成并缓存，poll 仅从内存缓存取回，timeout/poll_interval 形参保留兼容实际未使用）；成功 → `{image_path, task_status: completed}` + `set_entity_lookbook` 回写实体文件；失败 → task_status=failed。
   - 返回 `{"total": 本次张数, "completed": 全会话 completed 数}`（completed 统计自 `list_lookbook(session_id)` 全表）。

### 单张重生成（ScriptWorkflow.regenerate_lookbook_image）

校验 `row["script_session_id"] == session_id`（否则抛 `素材图不存在`）→ ImageTaskService.run_single：update task_status=processing（可选同时改写 prompt）→ submit + poll 单张 → 成功回写 image_path 与实体引用，返回最新行。与批量路径不同：此路径生图失败/提交失败直接抛 WorkflowError（run 流结束报错），而非静默置 failed。

### 完成步骤（ScriptWorkflow.complete_lookbook）

`ensure_can_execute(session_id, "lookbook_images")` 校验前置步骤链 → `save_step_result(session_id, "lookbook_images", {"completed": True}, success=True)`。无任何定妆照数量校验（数量校验只在前端按钮 disabled 层面）。

### Prompt 模板（backend/prompts/lookbook_prompts.md，2026-09-21 大改）

由 `backend/core/services/prompt_manager.py` 的 PromptManager 管理（`{{var}}` 占位符字符串替换，保存即覆盖）。模板要点：

- **第一步定风格**：用户在 style_prompt 明确指定 → 严格遵循；未指定 → Agent 按剧本题材自行判断（现实/生活流/悬疑/治愈 → 真实写实照片感；青春热血/奇幻/校园动画 → 2D 动漫；合家欢/科幻/拟人化 → 3D 渲染；搞笑/鬼畜/拼贴 → 风格化处理），且本次全部实体统一。
- **第二步写 prompt（英文→中文）**：**中文一段式自然语言 130-220 中文字**（术语全部中文化），理由是用户能直接读懂并修改；按实体类型分化——**人物 → 三视图设定图**（front/side/back 三视图、含身高比例尺标注、单人物）；**场景 → 全景**（无人物、标志元素齐全）。
- **输出**：严格 JSON 数组 `[{"entity_id", "prompt", "description"}]`，entity_id 只能来自清单、一个实体一条。
- style_prompt 未传时，用户 prompt 中渲染为「（用户未指定——请你根据剧本故事逻辑的题材与气质自行判断，并全剧统一）」。

### 持久层（backend/core/persistence/script_manager.py）

- `lookbook_images` 表：`image_id TEXT PRIMARY KEY`、`script_session_id`、`entity_id`、`prompt`、`description`、`image_path`、`task_id`、`task_status`（DEFAULT 'pending'）、`meta`（JSON 文本，读时缺省 `{}`）、`created_at`、`updated_at`。
- 状态机取值：`pending`（insert 初始）→ `processing`（提交成功）→ `completed` / `failed`（轮询结果）。
- `insert_lookbook` 新增 `image_path: str = ""` 与 `meta: Optional[dict]` 参数——允许直接落 completed 行（素材库复制导入用，引用同一远程 URL 无额外存储）。
- `update_lookbook` 字段白名单：`{prompt, description, image_path, task_id, task_status, meta}`，meta 经 dump_json 序列化，自动刷新 updated_at。
- `list_lookbook` 按 `created_at ASC` 排序，支持 entity_id / task_status 过滤；`list_completed_lookbooks`：全局查询所有会话 `task_status='completed' AND image_path != ''` 行（created_at DESC，素材库数据源）。
- 下游清空：`delete_script_data(script_session_id, keep_completed_lookbooks=False)`（级联重生成调用时 keep=True）——keep 模式仅删未完成/无图行，保留已完成有图行作素材库历史素材（返回 counts 含 `lookbook_images_kept`）；分集素材图两种模式都全删（与集号强绑定）。

### 工作区回写（backend/core/persistence/workspace_store.py）

`set_entity_lookbook(script_session_id, entity_id, image_id, image_path)`：定位实体文件 → 把 `lookbook_image_id`/`lookbook_image_path`/`updated_at` 合并进 frontmatter meta → 静态重写文件。文件只存引用，不存任务状态；实体找不到（已删）返回 False 不报错。

### 生图服务（backend/core/services/image_service.py）

- `build_image_service_from_model_config`：唯一生图服务工厂。model_config_id 非空按 id 精确取配置；否则取默认 image 模型；缺配置/缺 API Key/缺 Base URL/缺模型 ID 分别抛 `ImageModelNotConfiguredError`。
- `submit_image_task`：OpenAI 标准图片协议为同步生成，结果缓存在实例内存 `_sync_results`；未配置时返回 `{"success": False, "error": ...}` 而非抛异常。
- `poll_i2i_task`：从 `_sync_results.pop(request_id)` 取回图片 URL；任务不存在（已被取回/提交失败）返回失败。**注意：结果缓存在 ImageService 实例内存中**——批量生成路径中 submit 与 poll 共用同一实例无问题；服务重启则未取回结果丢失。

### 前端（frontend/src/components/script/StepLookbook.tsx）

- **前置门控**：`canExecute = completed_steps 含 episode_design`，不满足整卡显示「请先完成第 3 步：分集设计」；`isCompleted = completed_steps 含 lookbook_images`。
- **实体分组**：`entities.filter` 按 entity_type 分「人物」「场景」两组渲染卡片；线索/伏笔不出现（与后端校验一致）。无实体显示 Empty「暂无实体，请先完成分集设计」。
- **单卡片状态**：`imageByEntity`（useMemo）取实体当前素材图行——优先 `entity.lookbook_image_id` 指向的行，否则该实体最新一条（rows[rows.length-1]）。展示态：completed 且有 image_path → Image（imageSrc 处理：http(s) 原样，本地相对路径补 `/`）；pending → 「排队中」Spin；processing → 「生成中」Spin；failed → 「生成失败」；无 → 「暂无素材图」。
- **从素材库选择（新）**：每个实体卡片均有「从素材库选择」按钮（已有图/未生成两处入口）→ `setLibraryEntity(e)` 打开 LookbookLibraryModal → 拉分组（过滤目标实体当前已锚定图、源实体失效标注「实体已失效」）→ 单选 →「绑定到实体」`importLookbookImage(sessionId, entity_id, image_id)` → `handleImported` 同时刷新素材列表和实体列表（frontmatter 锚点已变）。
- **生成/重生成弹窗**：TextArea 提示词（placeholder 示例：纪实摄影质感，自然光，真实生活感，35mm 胶片；生成时留空由 Agent 生成、重生成清空则沿用原 prompt）+ Select 生图模型（modelApi.list('image') 拉取，标注默认；allowClear，空=默认生图模型）。确认后**单实体**调用：`generateLookbook(sessionId, [entity.entity_id], promptText, modelConfigId)` 或 `regenerateLookbookImage(sessionId, imageId, promptText || undefined, modelConfigId)`；记录 `entity_id → run_id` Map。
- **进度与轮询**：卡片内嵌 `AgentRunProgress`（runId 驱动，onDone 清 run 并刷新）；`usePolling` 2s 间隔，启用条件 `runs.size > 0 || 存在 pending/processing 图片`，刷新 loadImages + loadEntities。
- **删除**：Popconfirm 确认 → `deleteLookbookImage` → 刷新列表（不刷新实体）。
- **完成本步骤**：按钮 disabled 条件 `isCompleted || images.length === 0`（前端兜底：至少生成过一张）；点击 `completeLookbook` → message「第 4 步已完成」→ refreshSession。
- 挂载：`frontend/src/pages/ScriptWorkflowPage.tsx`（约 109 行）渲染；`frontend/src/components/script/index.ts` 导出。
- TS 类型 `LookbookImage`（frontend/src/types/index.ts 约 95 行）：image_id/script_session_id/entity_id/prompt/description/image_path/task_id?/task_status/meta?/created_at/updated_at。

## 依赖与复用关系

- 依赖: StepWorkflowBase（require_step_data/ensure_can_execute 步骤守卫，backend/core/agents/workflow_base.py）；run_agent/AgentRunOptions（backend/core/agent_sdk/wrapper.py）；PromptManager（backend/core/services/prompt_manager.py，渲染 backend/prompts/lookbook_prompts.md）；ImageService 工厂 build_image_service_from_model_config（backend/core/services/image_service.py，按「模型管理」配置构造）；start_agent_run/AgentRunRegistry（backend/deps.py + backend/core/agent_sdk/registry.py，异步 run + run_id）；WorkspaceStore（实体文件读写）；IMAGE_REQUEST_TIME_GAP（backend/core/config.py，12 秒提交间隔）；前端 antd（Card/Modal/Select/Image/Popconfirm 等）、usePolling（frontend/src/hooks/usePolling）、AgentRunProgress、useScriptSessionStore、imageSrc（frontend/src/utils/imageSrc.ts）
- 被依赖: 核心素材图是后续分镜/视频工作流的视觉锚点——`backend/core/services/script_context_service.py` 的 `fetch_lookbook_images` 直查 `list_lookbook(task_status="completed")` 并以 `lookbook_{image_id}` 形态并入分镜素材池（image_type='lookbook'）；`backend/core/agents/storyboard.py` 将素材图作为独立素材组供分镜引用（素材池 ID 规则 `lookbook_lb_*`）；实体卡上下文对已有素材图的实体标注「已有素材图，勿重复生成」。实体 frontmatter 的 lookbook_image_id/path 引用主要供前端 StepLookbook 展示与迁移脚本使用
- 可复用组件: ImageTaskService 生图状态机（run_batch/run_single）统一核心素材图批量/单张重生成/分集素材图三处；`_require_default_image_model` 前置校验被多条生图路由复用

## 注意事项

- **前后端批量能力不对齐**：后端 `generate_lookbook` 支持一次勾选多实体批量生成（entity_ids 列表 + 逐张间隔提交），但前端弹窗按单卡片触发、每次只传 `[entity.entity_id]` 一个实体；批量入口当前未在 UI 暴露。
- **生图结果存内存缓存**：ImageService 的 OpenAI 协议为同步生成、结果缓存在实例 `_sync_results`；poll_i2i_task 的 timeout=180/poll_interval=5 形参保留兼容但未使用。服务重启后未轮询取回的任务结果丢失（DB 停在 processing）。
- **失败不重试**：批量路径中单张提交失败/生成失败只置 task_status=failed 并记日志，不自动重试；重生成路径失败则抛错给 run 流。
- **complete 无数量后端校验**：complete_lookbook 仅校验步骤链，不校验是否有定妆照；「至少一张」约束仅在前端按钮 disabled（直接调 API 可空完成）。
- **重复生成产生多行**：同一实体重复生成会 insert 新行（旧行保留），前端展示按实体引用/最新行取；delete_lookbook 只删 DB 行，不清实体 frontmatter 引用（实体引用由下次生成成功覆盖）。
- **prompt 风格统一性**：模板要求「本次生成的所有实体统一风格」；但分多次单实体生成时（当前前端形态），每次 Agent 独立判断风格，若用户未填 style_prompt 可能出现风格漂移——模板通过 story_logic 注入缓解但不强制跨批次一致。
- **step 编号差异**：lookbook_prompts.md frontmatter 注释为 `step: 5`（prompt 管理器内含素材图等更多模板的排序），而工作流步骤名为第 4 步 lookbook_images，二者编号体系不同，勿混淆。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析自动生成 |
| 2026-09-21 | 同步重构 — 「定妆照」改「核心素材图」；生图 prompt 英文→中文（130-220 字，人物三视图/场景全景）；生图状态机统一至 ImageTaskService（run_batch/run_single）；新增素材库（GET lookbook/library + POST lookbook/import + LookbookLibraryModal）；script_manager 增 list_completed_lookbooks/insert_lookbook(image_path,meta)/delete_script_data(keep_completed_lookbooks)；级联重生成保留已完成素材 |
