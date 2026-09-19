---
name: 剧本创作工作流
摘要: 前端 /script 页面 + 后端 /api/v1/script-sessions 实现剧本创作 4 步向导（故事构思对话→故事大纲→分集设计→定妆照），markdown 产物落 workspace story 树（权威源），DB 只存会话/步骤状态与生图任务；第 1 步 SSE 请求内直跑，第 2/3/4 步经 AgentRunRegistry 后台 run + /agent-runs 观流。
tags: 剧本工作流, 后端API, 前端页面, AgentSDK, SSE, workspace文件化
---

# 剧本创作工作流

**状态:** 已完成
**最后更新:** 2026-09-19

## 功能概述

剧本创作智能体：4 步向导（与视频生成工作流相互独立、共用基础设施）——

1. **story_ideation 故事构思**：与 AI 多轮对话盘问（Agent SDK resume 多轮会话），finalize 收敛产出「故事逻辑」
2. **story_outline 故事大纲**：单次 agent run 产出 markmap markdown 思维导图（可人工编辑）
3. **episode_design 分集设计**：agent 通过进程内 MCP 工具（upsert_character/scene/clue/foreshadow + save_episode）注册全局实体并逐集落盘（增量可见），含集号连续/引用校验/伏笔因果校验
4. **lookbook_images 定妆照**：agent 单轮出英文生图 prompt，后端确定性生图（间隔提交 + 并发轮询），手动确认完成

两种运行形态（见 script_sessions.py 模块 docstring）：
- **形态 A（第 1 步对话/finalize）**：SSE 请求内直跑（`_sse_direct`），客户端断开触发 interrupt 优雅终止（5 秒宽限后强取消）
- **形态 B（第 2/3/4 步生成）**：POST 立即返回 `{run_id}`，前端连 `/api/v1/agent-runs/{run_id}/events` 观流（缓冲回放 + 实时 + seq 断线续传），生成期间分集列表 2s 轮询

数据存储采用**文件化工作区**（文件为权威数据源）：markdown 产物（story_logic/outline/episodes/entities）落 `workspace/{剧名}-{剧本会话id前8}/` story 树；SQLite 只存会话/步骤状态（薄 envelope 定位指针）、构思对话回放与 resume 句柄、定妆照任务状态机。`backend/core/services/workspace_projection.py` 把「文件 + DB 薄 envelope」投影回旧 step_results JSON 形状（API 响应结构零改动）。

前端为路由 `/script`（App.tsx 注册）的 `ScriptWorkflowPage`，antd Steps 4 步向导，步骤内容 keep-alive（仅 display:none 隐藏，切步骤不断开 SSE、不丢生成进度）；会话 ID 同步到 URL query（刷新恢复）。

## 核心代码路径

- `backend/api/v1/script_sessions.py` — API 层：`/api/v1/script-sessions` 下会话 CRUD、4 步全部路由、实体库 CRUD 与引用反查、`_sse_direct` SSE 直跑包装
- `backend/core/agents/script_workflow.py` — 业务核心：`ScriptWorkflow(StepWorkflowBase)`，4 步实现、分集强校验（`_validate_episode`/`_validate_episode_refs`）、分集设计 MCP 工具集（`_build_design_mcp_server`）、定妆照生成
- `backend/core/persistence/workspace_store.py` — 文件化工作区存储：story 树目录管理、frontmatter+markdown 读写、原子写 + per-story 线程锁、ID 白名单正则（`EPISODE_ID_PATTERN`/`ENTITY_ID_PATTERN`）
- `backend/core/persistence/script_manager.py` — DB 侧任务表：`script_entities`/`episodes`/`lookbook_images`/`episode_material_images` 建表与定妆照 CRUD（markdown 权威源在 store，此层仅状态机）
- `backend/core/persistence/session_manager.py` — `SCRIPT_STEPS` 4 步定义与 `SessionManager`（会话/步骤状态，构造注入 steps）
- `backend/core/services/workspace_projection.py` — 投影层：`script_step_results`/`script_title`（文件权威源 → 旧 JSON 形状，老 DB 数据 fallback）
- `backend/api/v1/agent_runs.py` — 通用 agent run 端点：`GET /{run_id}/events` SSE 观流（seq 增量回放）、`GET /{run_id}` 轮询兜底、`POST /{run_id}/cancel`
- `backend/deps.py` — 依赖注入：`get_script_session_manager`（SessionManager(steps=SCRIPT_STEPS) 单例）、`get_script_manager`、`get_workspace_store`、`load_script_session`（不存在 404 / 非剧本会话 400）、`start_agent_run`（统一 run_id 响应）
- `backend/main.py` — 路由挂载（`/api/v1/script-sessions`、`/api/v1/agent-runs`）与 `ScriptWorkflowError` 全局异常 handler（→ HTTP detail，状态码由异常携带默认 400）
- `frontend/src/pages/ScriptWorkflowPage.tsx` — 页面骨架：Steps 导航 + 4 步组件 keep-alive + URL 会话恢复
- `frontend/src/components/script/StepIdeationChat.tsx` — 第 1 步：多轮对话（fetchSSE 直连形态 A）、finalize 收敛、story_logic 人工编辑
- `frontend/src/components/script/StepOutline.tsx` — 第 2 步：大纲生成（run_id 观流）+ mindmap 编辑
- `frontend/src/components/script/StepEpisodeDesign.tsx` — 第 3 步：全量/单集重设计（run 观流 + 2s 轮询分集列表）、分集编辑、实体库管理
- `frontend/src/components/script/StepLookbook.tsx` — 第 4 步：勾选实体生成定妆照、单张重生成、手动确认完成
- `frontend/src/components/script/AgentRunProgress.tsx` — 形态 B 通用观流组件：连 `/api/v1/agent-runs/{run_id}/events`（lastSeq 断线重连）、思考折叠、取消
- `frontend/src/api/client.ts` — `scriptApi`（约 335 行起，全部 REST 调用）与 `agentRunApi`（约 477 行，cancel）
- `frontend/src/api/sse.ts` — `fetchSSE`：fetch + ReadableStream 解析 SSE（形态 A 直连用）
- `frontend/src/stores/scriptSessionStore.ts` — zustand 会话状态（loadSession/transformScriptSession）
- `backend/prompts/` — 提示词模板：`script_ideation.md`、`script_ideation_finalize.md`、`script_outline.md`、`episode_design.md`、`lookbook_prompts.md`（`prompt_manager.render` 按名渲染）

## 关键逻辑说明

### 后端 API（backend/api/v1/script_sessions.py，挂载前缀 /api/v1/script-sessions）

| 路由 | 形态 | 行为 |
|------|------|------|
| POST /script-sessions | - | 创建（uuid4 会话）+ 即刻 `ensure_story` 建 workspace story 树 |
| GET /script-sessions | - | 列表（title 经 workspace_projection.script_title，文件 outline.title 优先） |
| GET/DELETE /script-sessions/{sid} | - | 详情（step_results 经投影）/ 删除（session + script 数据 + story 树三处同删） |
| POST /{sid}/ideation/message | A | 一轮构思对话（SSE 直跑，resume agent 会话） |
| POST /{sid}/ideation/finalize | A | 收敛故事逻辑（同 resume 会话），完成第 1 步 |
| GET/PUT /{sid}/ideation | - | 构思历史（messages + story_logic）/ 人工编辑 story_logic（不推进不重置，story_logic 空 400） |
| POST /{sid}/outline/generate | B | 生成大纲 → run_id；前置校验第 1 步完成否则 400 |
| GET/PUT /{sid}/outline | - | 大纲读取（投影）/ 人工编辑（集数与已存分集不一致时返回 warning） |
| POST /{sid}/episodes/generate | B | 全量分集设计 → run_id；前置校验第 2 步完成 |
| POST /{sid}/episodes/regenerate | B | 单集重设计 → run_id（episode_id 不变，不破坏下游引用；run label 为 `episode_redesign_{id}`） |
| GET /{sid}/episodes[/{eid}] | - | 分集列表/详情（生成期间前端 2s 轮询） |
| PUT /{sid}/episodes/{eid} | - | 人工编辑（refs 类字段走与 save_episode 相同引用校验） |
| DELETE /{sid}/episodes/{eid} | - | 仅允许删除最后一集（保持集号连续）否则 400 |
| GET/POST /{sid}/entities | - | 实体列表（可按类型过滤）/ 人工新增更新（ID 后端分配，ValueError → 400） |
| PUT/DELETE /{sid}/entities/{eid} | - | 更新（404 校验归属）/ 删除（被任何分集引用时 400 拒绝） |
| GET /{sid}/entities/{eid}/references | - | 引用反查：人物/场景→出场，线索/伏笔→action 值 |
| POST /{sid}/lookbook/generate | B | 勾选实体生成定妆照 → run_id；`_require_default_image_model`：未指定配置且无默认生图模型直接 400 |
| POST /{sid}/lookbook/complete | - | 手动确认完成第 4 步（按需勾选无自然终点） |
| GET /{sid}/lookbook | - | 定妆照列表（可按 entity_id/task_status 过滤） |
| POST /{sid}/lookbook/{iid}/regenerate | B | 单张重生成 → run_id（可选改 prompt） |
| DELETE /{sid}/lookbook/{iid} | - | 删除定妆照记录 |

- 路径参数 ID 白名单：`EPISODE_ID_PATH`/`ENTITY_ID_PATH`（FastAPI Path pattern，422 快速失败防 glob 元字符注入），pattern 与 store 层/schema 共用同一常量。
- 业务异常 `ScriptWorkflowError(message, status_code=400)` 由 main.py 全局 handler 统一转 `{"detail": ...}`，路由层不逐个 try/except。
- `_sse_direct`：agent 事件经 asyncio.Queue 转 SSE 流；finally 中客户端断开先 interrupt（优雅终止）、`asyncio.wait_for(shield(task), 5)` 宽限后强取消；事件依次 `item.to_sse(0)`，结束发 `final`/`error` 与 `[DONE]`。

### 工作流核心（backend/core/agents/script_workflow.py）

- **第 1 步构思**：`ideation_message` 用 `run_conversation`（agent_session_id resume 多轮，max_turns=10）；对话轮次不推进步骤（success=False 存中间态），消息副本存 DB 供前端刷新还原。`ideation_finalize` 同会话注入 finalize 模板收敛，story_logic 写工作区文件 `00-ideation/story-logic.md`（权威源），DB 去掉 story_logic 只留回放与句柄。
- **第 2 步大纲**：`run_agent` 单次（max_turns=2，SCRIPT_OUTLINE_SYSTEM）；输出 `extract_markdown` + `is_valid_mindmap` 校验（非 markdown 层级报错重试）。**重生成级联清下游**：`clear_steps_after`（步骤）+ `store.delete_story_content`（分集/实体文件）+ `scm.delete_script_data`（定妆照/素材图任务表）。大纲写 `01-outline/outline.md`（根标题即剧名，story 目录随剧名正名），DB 只存薄 envelope `{"_artifact": "workspace", "path": "workspace/.../01-outline/outline.md"}`。
- **第 3 步分集设计**：
  - MCP 工具集（`create_sdk_mcp_server(name="script_design")`）：`upsert_character/scene/clue/foreshadow`（注册/更新实体，返回分配 ID）+ `save_episode`（严格校验后落盘）；错误以 `_text_error` 文本返回给 agent 自纠，不抛异常。
  - 读侧：`tools=READ_ONLY_TOOLS`（Read/Grep/Glob）+ `cwd=store.story_cwd()`，agent 在剧本目录内自主检索工作区文件（MAP.md 目录地图 + outline + 已存分集/实体卡）。
  - max_turns 按集数估算：`max(20, min(10 + 3*集数, 200))`。
  - `save_episode` 强校验（`_validate_episode`）：集号连续（ep_01 起、顺序 = 已存+1）；每集至少 1 人物 1 场景；引用存在性/前缀类型匹配（chr/scn/clu/fs）；action ∈ plant/develop/reveal/payoff；伏笔 payoff 集号必须晚于 plant；线索 reveal 前必须有更早集 plant/develop；ending_summary 100-300 字、conflict_chain/causality_chain ≤2000 字、story_progress ≤600 字；末集伏笔回收检查（已 plant 从未 payoff 必须补，实体 meta `open_ending=true` 豁免）。
  - 全量生成完成后核对 `len(episodes) == 大纲集数`（`_count_outline_episodes`：匹配 `##/### 第 N 集|EP N` 标题，兜底 `##` 分支数），不足抛错；单集重设计不推进步骤、只允许覆写该集（工具层拦截其他集号）。
  - 单集重设计 prompt 注入：上一集结尾摘要/因果链、旧版设计（含引用）、下一集梗概/因果、已注册实体清单（要求复用 entity_id）。
- **第 4 步定妆照**：仅 character/scene 可生成（clue/foreshadow 400）；agent 单轮（max_turns=2，LOOKBOOK_PROMPTS_SYSTEM）+ `extract_json_array` 解析英文 prompt（缺漏实体用「名称+设定」兜底 prompt）；生图复用 ImageService（`build_image_service_from_model_config`）：逐张间隔 `IMAGE_REQUEST_TIME_GAP`（12 秒）提交，`asyncio.gather` 并发轮询（timeout=180s，间隔 5s），状态机 processing→completed/failed 写 `lookbook_images` 表，成功后回写实体卡 lookbook 字段。生图参数全剧统一 `LOOKBOOK_VIDEO_PARAMS = VideoParams(resolution="1080p", aspect_ratio="16:9")`。

### workspace 文件化（backend/core/persistence/workspace_store.py）

目录树（一个剧本会话一棵 story 树）：

```
workspace/{剧名}-{剧本会话id前8}/
├── MAP.md                          目录地图（自动渲染）
├── 00-ideation/story-logic.md      故事逻辑
├── 01-outline/outline.md           全剧大纲（mindmap，根标题即剧名）
├── 02-episodes/ep_NN-标题.md       分集设计
├── 03-entities/{chr|scn|clu|fs}_NNN-名字.md   全局实体卡
└── 04-storyboards/ep_NN/vs-{视频会话id前8}/   （视频工作流的分镜，非本功能写入）
```

- 关联信息（引用/edited 标志等）存 frontmatter，正文 markdown（分集正文固定小节：梗概/矛盾链/因果链/结尾摘要/节点进展）；返回 dict 键与旧 SQLite row 一致（API 零改动）。
- 原子写（tmp + os.replace）+ per-story RLock；next_entity_id 跨会话全局分配用进程级锁。
- ID 白名单：`EPISODE_ID_PATTERN = ^ep_[0-9]{2,}$`、`ENTITY_ID_PATTERN = ^(chr|scn|clu|fs)_[0-9]{3,}$`（防路径/glob 注入；正则用 `\Z` 绝对锚定 + ASCII 显式类）。
- story 目录定位：sessions.workspace_path 锚点优先，glob `*-{sid8}` 兜底；正文值中的行首 `## ` 做双射转义防与小节定界符冲突。
- workspace 根目录为项目根下 `workspace/`（backend/core/config.py 的 `WORKSPACE_DIR`，启动时自动 mkdir）。

### 前端（frontend/src/pages/ScriptWorkflowPage.tsx + components/script/*)

- Steps 4 项（故事构思/故事大纲/分集设计/剧本定妆照）；viewStep 纯前端浏览切换（不回写后端），会话切换时同步到 current_step；4 个步骤组件 keep-alive（`display:none` 隐藏而非卸载）。
- 会话 ID 双向同步 URL `?session_id=`（history.replaceState），挂载时从 URL 恢复 loadSession。
- 第 1 步（形态 A）：`fetchSSE`（frontend/src/api/sse.ts）直连 POST 端点流式消费 AgentEvent（prompt/thinking/tool_use/text_delta/result/final/error），AbortController 取消。
- 第 2/3/4 步（形态 B）：POST 拿 run_id → `AgentRunProgress` 连 `GET /api/v1/agent-runs/{run_id}/events?seq=`（lastSeq 断线重连增量续传；结束哨兵 `done` 附终态供刷新）；分集设计期间另以 2000ms interval 轮询（usePolling）拉取分集列表与实体库，时间线逐集点亮。
- 状态管理 `useScriptSessionStore`（zustand）；API 封装 `scriptApi`/`agentRunApi`（axios baseURL `/api/v1`）。

## 依赖与复用关系

- 依赖: Agent SDK 封装（backend/core/agent_sdk：run_agent/run_conversation/AgentEvent/READ_ONLY_TOOLS，claude_agent_sdk 子进程 + ANTHROPIC_* env 注入）；AgentRunRegistry（后台 run 注册表，backend/core/agent_sdk/registry.py）；ImageService（backend/core/services/image_service.build_image_service_from_model_config，模型配置来自 image_models 默认生图模型）；PromptManager（backend/core/services/prompt_manager，模板目录 backend/prompts/）；SessionManager/BaseSQLiteManager（data/sessions.db）；前端 antd（Steps/-message）、axios、zustand
- 被依赖: 视频生成工作流从剧本分集进入（backend/api/v1/sessions.py 用 schemas/script.py 的 CreateVideoSessionFromScriptRequest 创建视频会话，script_session_id+episode_id 定位分集；frontend/src/pages/WorkflowPage.tsx 为其页面，backend/core/agents/storyboard.py 分镜写 story 树 04-storyboards/）；模型管理功能（生图默认模型校验 `_require_default_image_model`）
- 可复用组件: `AgentRunProgress`（任何 run_id 观流通用）；`fetchSSE`（任何 POST SSE 直跑）；`_sse_direct`（形态 A 路由包装范式，StoryboardWorkflow 同款）；`StepWorkflowBase`（步骤守卫 require_step_data/ensure_can_execute）

## 注意事项

- **文件为权威源、DB 为投影**：story_logic/mindmap 等读取一律先工作区文件、DB 老数据仅 fallback（workspace_projection.py 注释：cutover 后可移除）；定妆照任务状态、构思 messages/agent_session_id 始终以 DB 为准。
- **重生成级联清空**：大纲重生成会清空分集/实体/定妆照全部下游数据（三处：步骤行 + 工作区文件 + DB 任务表），前端无二次确认时不慎重生成不可恢复（需注意 UX）。
- **ID 安全是硬约束**：episode_id/entity_id 走白名单正则（API Path 422 / pydantic Field pattern / store 层 `_require_*` 三层同 pattern 常量），改动须三处同步。
- **形态 A 与形态 B 语义不同**：A 断开即取消（请求生命周期绑定）；B 的 run 在后台继续，断线重连可续传（seq）。
- **分集生成是长任务**：max_turns 按集数线性估算（上限 200），全集数较多时单 run 时间长；中断只能经 `/agent-runs/{run_id}/cancel`（触发 interrupt 自然终止）。
- **伏笔/线索校验依赖保存顺序**：agent 必须从 ep_01 顺序保存；人工编辑 refs 走同一校验核心 `_validate_episode_refs`（合并其他集做全局 plant/payoff 计算）。
- **定妆照生图模型**：未传 model_config_id 且未配置默认生图模型时 400（提示去「模型管理」配置）；生图间隔 12s/张为限流保护（IMAGE_REQUEST_TIME_GAP）。
- **prompt 模板热加载**：backend/prompts/*.md 由 PromptManager 扫描（可通过 /api/v1/prompts 管理页面编辑），模板名硬编码于 script_workflow.py（script_ideation/script_ideation_finalize/script_outline/episode_design/lookbook_prompts）。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析自动生成（feat/create_story 分支，含文件化改造） |
