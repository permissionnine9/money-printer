---
name: 会话步骤状态机逻辑
摘要: 两条 4 步工作流以 SQLite step_results 的 _success 标志驱动线性推进、回退与级联清空
tags: SessionManager, 步骤状态, 工作流, _success, 级联清空
---

# 会话步骤状态机逻辑

**最后更新:** 2026-09-21

## 逻辑概述

系统有两条并行的 4 步工作流，共用同一个 `SessionManager`（`backend/core/persistence/session_manager.py`），仅步骤序列不同（构造参数 `steps` 注入）：

- 剧本创作 `SCRIPT_STEPS`：`story_ideation` → `story_outline` → `episode_design` → `lookbook_images`
- 视频生成 `VIDEO_STEPS`：`select_episode` → `storyboard_outline` → `segment_management` → `generate_videos`

两个管理器单例（`backend/deps.py` 的 `get_session_manager` / `get_script_session_manager`，均 `lru_cache`）共用同一 SQLite 文件 `data/sessions.db`（WAL 模式，见 `backend/core/persistence/base.py`），靠 `sessions.workflow_type`（'video' | 'script'）区分归属。状态持久化在三张表：`sessions`（current_step / status / workflow_type / script_session_id / source_episode_id / workspace_path 溯源列）、`step_results`（`UNIQUE(session_id, step_name)`，result_data 为 JSON）、`session_assets`。

状态机核心语义在 `save_step_result`：result_data 内写 `_success` 标志；`success=True` 时 upsert 步骤结果并把 `current_step` 推进到下一步（`_get_next_step` 对最后一步返回 None，即 current_step 置 NULL）；`success=False` 时只记录结果、current_step 不动。`get_completed_steps` / `is_step_completed` 只认 `_success=True` 的行（旧数据无该键默认 True）。执行门禁 `can_execute_step` 不看 current_step，而是线性校验目标步骤之前的所有前驱步骤均 `is_step_completed`。回退与重做靠三个原语：`clear_steps_after`（删某步之后的全部结果并把 status 拉回 'active'）、`clear_step_result`（删单步结果）、`reset_current_step`（把 current_step 写回指定步骤）。另有 `save_aux_state`（约 :192 — 辅助状态如 comfyui_import，复用 step_results 表但**不推进状态机**；供 video_workflow 的 ComfyUI 导入状态 `_get_imported_state` 使用）与 `rollback_completion`（约 :468 — 回退完成态）两个辅助原语。

产物遵循「文件为权威源、DB 留薄 envelope」：markdown 类产物（故事逻辑/大纲/分镜）写 workspace 文件，DB 的 step_results 只存薄 envelope（`{_artifact:'workspace', path}`）+ `_success`/`_cancelled` 标志或进度统计，读取时经 `backend/core/services/step_payload.py` 投影回 JSON 形状（文件为唯一权威源，已无 DB 旧完整数据 fallback，详见 logics/dual-persistence-projection.md）。

## 关键流程

**步骤推进（save_step_result success=True）**

1. 剧本第 1 步 — 两条完成路径：① `ideation_finalize`（`backend/core/agents/script_workflow.py`）由 LLM 收敛故事逻辑：story_logic 写工作区文件后 `save_step_result("story_ideation", ..., success=True)`；② `adopt_story_logic`：用户「采纳为故事逻辑」直接完成第 1 步，不经 LLM finalize 收敛。完成即 current_step 推进到 story_outline。对话轮次 `ideation_message` 不推进：首轮 `save_step_result(success=False)`（存 resume 句柄）、后续轮 `update_step_result`（保留原 `_success`、不动 current_step）
2. 剧本第 2 步 — `generate_outline`：先 `clear_steps_after("story_outline")` + 工作区 `delete_story_content` + DB 素材图/素材任务 `delete_script_data` 级联清下游，大纲写文件后 `save_step_result` 只存薄 envelope（指向 `01-outline/outline.md`）
3. 剧本第 3 步 — `generate_episodes`：全量模式先级联清下游（clear_steps_after + 删工作区 + 删 DB），agent 经 MCP 工具逐集落库，集数校验通过后 `save_step_result("episode_design", success=True)`；单集重设计（`regenerate_episode_id` 非空）不推进不清理
4. 剧本第 4 步 — `complete_lookbook`：手动确认（按需勾选无自然终点），`save_step_result("lookbook_images", {"completed": True}, success=True)`；此为最后一步，current_step 置 NULL
5. 视频第 1 步 — `step_select_episode`（`backend/core/agents/workflow_v2.py`）：校验剧本会话 `episode_design` 已完成 + 分集存在 + `VideoParams` 合法后 `save_step_result(success=True)`（会话创建入口 `POST /api/v1/sessions/from-script` 同样校验剧本 episode_design 完成）
6. 视频第 2 步 — `generate_outline`（`backend/core/agents/storyboard.py`）：`ensure_can_execute`（workflow_base 前驱校验）后先 `clear_steps_after("storyboard_outline")`，`write_storyboard` 清目录重写（级联重置配置与提示词），再 `save_step_result(success=True)`
7. 视频第 3 步 — 完成态粒度已从「整步完成」演进为**单分镜完成态**：`complete_segment`（storyboard.py 的 StoryboardWorkflow）按分镜 index 逐个置 completed 标志（对应前端 `completeSegment(sessionId, index, completed)`），segment_management 步骤的完成由单分镜完成态承载
8. 视频第 4 步 — `POST /api/v1/steps/{session_id}/videos`（`backend/api/v1/steps.py`）：`can_execute_step` 校验后先落「生成中」快照（`_generating=True`、`_success=False`、全部视频 pending），经 BackgroundTasks 后台跑 `workflow.step_generate_videos`；成功 `save_step_result(success=True)` + `update_session_status("completed")`，失败 `save_step_result(success=False)`。前端 `Step6Videos.tsx` 每 3 秒轮询会话详情看进度（不走 SSE 观流）

**失败与中间态（_success=False，current_step 不动）**

1. 构思首轮对话 — `save_step_result(success=False)`：记录 agent_session_id/messages 供 resume，但步骤未完成，`can_execute_step("story_outline")` 拒绝（API 层 script_sessions.py 直接 `is_step_completed` 校验并 400「请先完成故事构思」）
2. 视频生成中 — `_generating=True` + `_success=False`：steps.py 先存初始 pending 状态，后台任务逐段更新进度快照；取消接口 `cancel-videos` 经 `set_step_cancelled` 写 `_cancelled=True` 标志
3. 生成失败 — `save_step_result(failure_data, success=False)`：错误信息留在 result_data.error，current_step 停在第 4 步可重试

**回退与重做（人工编辑触发）**

1. 人工编辑导图（剧本 `update_outline` / 视频 storyboard `update_outline`）— `update_step_result` 只更新 envelope 不推进不重置
2. 视频导图分镜有变化（title/outline 改动或增删）且 segment_management 已完成 — 三连回退：`clear_step_result("segment_management")` + `clear_steps_after("segment_management")` + `reset_current_step("segment_management")`，需重新确认（`_save_segment_change` 对分镜配置/参考图变化同样走这三连）
3. 重生成大纲/分集/分镜 — 先 `clear_steps_after` 级联清下游，再重写
4. 视频重新生成 — `POST /api/v1/steps/{session_id}/regenerate-videos`：`is_step_completed` 双重校验后 `reset_current_step("generate_videos")`，旧视频保留 `_old_video_path` 备份字段；`POST .../restore-videos-backup` 可恢复备份并重新置 `_success=True`
5. `clear_steps_after` 附带把 status 从 completed 拉回 active

**门禁与加载（API 层）**

1. `load_video_session` / `load_script_session`（backend/deps.py）— 会话不存在 404；剧本侧类型不符 400
2. 生成类端点前置校验 — script_sessions.py（挂载于 `/api/v1/script-sessions`）各步生成入口直接 `is_step_completed(前驱)` 校验（如 outline/generate 校验 story_ideation）；steps.py（挂载于 `/api/v1/steps`）分镜大纲/视频生成入口用 `can_execute_step`；workflow 层再经 `workflow_base.ensure_can_execute` 兜底（守卫失败抛业务异常，main.py 全局 handler 转 400 detail）
3. legacy 标记 — `GET /api/v1/sessions`（sessions.py list_sessions）：completed_steps 非空且（无 select_episode 结果 或 含已删除旧步骤 generate_segment_scripts / generate_episode_reference_images / generate_segment_frames 结果）→ `legacy=True`，前端隐藏旧 5/7 步会话

**前端消费**

1. 后端步骤名 → 索引 — `frontend/src/stores/sessionStore.ts` 的 `stepNameToIndex`（STEP_NAME_TO_INDEX）与 `frontend/src/stores/scriptSessionStore.ts` 的 `scriptStepNameToIndex`（SCRIPT_STEP_NAME_TO_INDEX）；current_step 为 NULL（全部完成）时按 completed_steps 兜底：含最后一步 → 最后一步；否则视频侧兜底第一步（return 0）、剧本侧兜底第一个未完成步骤
2. 浏览步骤纯前端状态 — `frontend/src/pages/ScriptWorkflowPage.tsx` 的 viewStep 切换不回写后端；`frontend/src/pages/WorkflowPage.tsx` 生成完成推进 current_step 但不打断用户正在浏览的步骤；4 步组件 keep-alive（仅 display:none 隐藏，SSE 与生成进度保活）

## 涉及代码

- `backend/core/persistence/session_manager.py` — 状态机核心：SCRIPT_STEPS/VIDEO_STEPS 步骤序列、save_step_result / update_step_result / get_completed_steps / is_step_completed / can_execute_step / clear_steps_after / clear_step_result / reset_current_step / set_step_cancelled / update_session_status / create_session / list_sessions / delete_session（含 session_assets 资产表管理）；新增 save_aux_state（辅助状态，不推进状态机）/ rollback_completion（回退完成态）；已删除 delete_step_result / get_latest_session / is_step_cancelled
- `backend/core/persistence/base.py` — BaseSQLiteManager：`data/sessions.db` 默认路径、WAL 模式（多 manager 并发读写）、`_connect()` 为 @contextmanager 显式 conn.close()（修复 sqlite 连接 fd 泄漏——曾致进程堆积数百连接）、`_init_database` 同步改造、`_add_columns_if_missing` 旧表列迁移
- `backend/deps.py` — 视频/剧本两个 SessionManager 单例（共用 db）、load_video_session / load_script_session 加载守卫、start_agent_run
- `backend/core/agents/workflow_base.py` — StepWorkflowBase：require_step_data（未完成抛业务异常）/ ensure_can_execute（前驱校验）
- `backend/core/agents/script_workflow.py` — 剧本 4 步推进点：ideation_message（不推进）/ ideation_finalize（推进）/ generate_outline（级联清+推进）/ generate_episodes（全量推进、单集不推进）/ complete_lookbook（手动推进）
- `backend/core/agents/storyboard.py` — 视频第 2/3 步：generate_outline（级联清+推进）/ update_outline（变化回退 segment_management）/ _save_segment_change（配置变化回退）/ complete_segment_management（推进）
- `backend/core/agents/workflow_v2.py` — 视频第 1/4 步：step_select_episode（推进）、step_generate_videos（成功推进+置 completed、失败 _success=False）、_videos_snapshot 进度快照
- `backend/api/v1/steps.py` — 视频工作流端点（挂载于 `/api/v1/steps`）：第 4 步生成中状态落库、cancel-videos（_cancelled）、regenerate-videos（备份+重置）、restore-videos-backup
- `backend/api/v1/sessions.py` — 视频会话 CRUD（`/api/v1/sessions`）、POST /from-script（校验剧本 episode_design）、legacy 标记
- `backend/api/v1/script_sessions.py` — 剧本会话 CRUD 与 4 步端点（`/api/v1/script-sessions`，各步前置 is_step_completed 校验）
- `backend/core/services/step_payload.py` — 文件权威源 → step_results JSON 形状读投影（script_step_results / video_step_results / script_title；原 workspace_projection.py 已删除拆分，详见 logics/dual-persistence-projection.md）
- `frontend/src/stores/sessionStore.ts` — 视频会话 store：stepNameToIndex 步骤名转索引（NULL 兜底第一步）
- `frontend/src/stores/scriptSessionStore.ts` — 剧本会话 store：scriptStepNameToIndex（NULL 兜底第一个未完成步骤）
- `frontend/src/components/workflow/Step6Videos.tsx` — 视频第 4 步组件（文件名沿用旧序号）：3 秒间隔轮询会话详情，存在 pending 视频或 `_generating` 时启用
- `frontend/src/pages/ScriptWorkflowPage.tsx` / `frontend/src/pages/WorkflowPage.tsx` — 步骤导航消费方（viewStep 浏览态、keep-alive）

## 相关功能

- 创作剧本工作流（ScriptWorkflow 4 步）
- 视频创作工作流（VideoCreationWorkflowV2 4 步）
- SSE 事件流协议逻辑（剧本第 2-4 步与视频第 2/3 步生成观流；视频第 4 步为轮询例外）
- 文件化工作区权威存储（DB 薄 envelope 的权威源侧）

## 注意事项

- current_step 是展示/恢复用字段，不是执行门禁：门禁实际靠 `can_execute_step` 的前驱完成链；最后一步成功后 current_step 被置 NULL，前端 store 按 completed_steps 兜底显示
- `_success` 写在 result_data JSON 内而非独立列：`get_completed_steps` 逐行 json.loads 检查；无该键的旧数据默认 True（历史兼容）
- 两个 SessionManager 共用同一 db：`save_step_result` 校验 step_name 必须在本管理器 STEPS 内（非法抛 ValueError），跨工作流写会被拦，但 `get_all_step_results` 读侧不过滤（legacy 检测正利用旧步骤键的存在性）
- 视频第 4 步是唯一「先落失败态再后台执行」的步骤：依赖 `_generating`/`_cancelled` 内嵌标志记录进度与取消请求；但 `_cancelled` 目前只写不读——后台生成链路（step_generate_videos → comfyui_service）无任何消费方，实际不会中断生成（原 `is_step_cancelled` 全库无调用点，该方法已删除）。后台任务亦无恢复机制，进程重启后 DB 可能永久停在 _generating=True
- `save_aux_state` 复用 step_results 表存辅助状态（如 video_workflow 的 comfyui_import 导入状态，经 `_get_imported_state` 读取），但不推进状态机、不影响门禁——辅助状态与步骤完成态共用一张表靠键名区分
- `clear_steps_after` 只清 DB step_results 与 status，不清工作区文件/DB 核心素材图行——各调用方需自行组合 `delete_story_content` + `delete_script_data`（script_workflow 已组合；storyboard 靠 write_storyboard 清目录重写）
- 人工编辑（update_step_result）设计为「不推进不重置」，但视频侧导图编辑例外：分镜变化会主动回退 segment_management 完成态
- 单集重设计（regenerate_episode_id）与单张定妆照重生成均不推进步骤，只覆写产物
- legacy 会话（旧 5/7 步）仅从列表隐藏，GET 详情仍可访问；`_get_video_segments` 优先读旧 generate_segment_scripts 结果做兜底

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析生成（feat/create_story 分支现状：4 步双工作流 + 文件化 envelope） |
| 2026-09-21 | 4 步定义不变；新增 save_aux_state/rollback_completion，删除 delete_step_result/get_latest_session/is_step_cancelled；ideation 第二完成路径 adopt_story_logic；segment_management 演进为单分镜完成态 complete_segment；base.py _connect 改 @contextmanager 修 fd 泄漏；投影层 workspace_projection → step_payload（无 DB fallback） |
