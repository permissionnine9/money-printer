---
name: 视频创作工作流（视频会话与生成）
摘要: 视频 4 步工作流（选集/分镜大纲/分镜管理/生成视频）：POST /api/v1/sessions/from-script 从剧本建会话，步骤 API 驱动 StoryboardWorkflow 与 VideoCreationWorkflowV2（core/workflows/video_workflow.py），ComfyUI 整段时间轴生成视频（mock 兜底），支持取消/指定段生成/备份恢复/「导入到 ComfyUI」（UI 工作流写服务器）。
tags: 后端API, 视频生成, ComfyUI, 会话管理, 前端页面
---

# 视频创作工作流（视频会话与生成）

**状态:** 已完成
**最后更新:** 2026-09-21

## 功能概述

剧本创作工作流（script 链）的下游视频生产链：从已完成的剧本会话选一个分集创建视频会话，按 4 步流水线产出最终视频。

4 步序列（`VIDEO_STEPS`，定义于 backend/core/persistence/session_manager.py）：

1. `select_episode` — 从剧本选集，绑定分集设计与视频参数（resolution/aspect_ratio/max_segment_duration）
2. `storyboard_outline` — 分镜大纲（agent 生成导图 + 分镜列表，人工编辑 reconcile）
3. `segment_management` — 分镜管理（分镜形式/overlap 配置、参考素材图、提示词生成、单分镜完成态）
4. `generate_videos` — 视频生成（远程 ComfyUI 整段时间轴一次生成整条视频，mock 本地兜底）；支持 **segmentIndexes 指定段生成**、重新生成前自动备份、**「导入到 ComfyUI」**（上传素材 + 注入 timeline_data + UI 版工作流写服务器）

步骤 2/3 的分镜侧逻辑由 StoryboardWorkflow（backend/core/agents/storyboard.py）承担，详见分镜工作流文档；本文聚焦视频会话生命周期与步骤 1/4。

**模块位置（2026-09-21 迁移）**：视频生成链已从 `backend/core/agents/workflow_v2.py` 迁出至 **`backend/core/workflows/video_workflow.py`**（617 行；`backend/core/workflows/__init__.py` 导出，docstring 注明「自 agents 包迁出的非 agent 型工作流」）；类名仍为 `VideoCreationWorkflowV2`，构造新增 `store: WorkspaceStore` 注入。

整体数据流：前端 WorkflowPage（路由 `/`）→ stepApi/sessionApi（frontend/src/api/client.ts，baseURL `/api/v1`）→ backend/api/v1/sessions.py + backend/api/v1/steps.py（挂载 `/api/v1/sessions`、`/api/v1/steps`）→ VideoCreationWorkflowV2 / StoryboardWorkflow → SessionManager（SQLite data/sessions.db）+ WorkspaceStore（workspace/ markdown 权威源）→ VideoServiceComfyUI（backend/core/services/comfyui_service.py）。

## 核心代码路径

- `backend/api/v1/sessions.py` — 视频会话 CRUD：POST /from-script 从剧本建会话、GET 列表（legacy 会话标记、剧本会话过滤）、GET 详情（工作区投影 step_results）、DELETE
- `backend/api/v1/steps.py` — 视频 4 步工作流全部步骤端点；步骤 4 的生成/取消/恢复备份路由与初始状态构建（`_build_initial_videos` 等）在本文件
- `backend/core/workflows/video_workflow.py` — `VideoCreationWorkflowV2`：step_select_episode（选集绑定 video_params）、`_get_video_segments`（读工作区分镜）、`run_generate_videos_sync`（同步生成入口）、`mark_videos_generating`/`restore_videos_backup`（生成中状态与备份恢复）、`prepare_comfyui_import`/`_execute_imported_videos`/`_get_imported_state`（ComfyUI 导入）、`_auto_global_prompt`（全局提示词提取）、`_collect_generation_materials`（素材收集）、`_resolve_generation_segments`/`_configured_segment_indexes`（指定段解析）
- `backend/core/agents/storyboard.py` — `StoryboardWorkflow`：步骤 2/3 的分镜大纲生成/编辑、分镜配置、素材池、提示词生成（本文不展开）
- `backend/core/models/video_models.py` — 领域模型：`VideoParams`（分辨率/宽高比/最大分片时长 5-30s/overlap 0-5s）、`StoryboardSegment`、`SegmentReferenceImage`
- `backend/core/services/comfyui_service.py` — `VideoServiceComfyUI`/`TimelineBuilder`/`ComfyUIClient`：timeline_data 构造与校验、素材上传、/prompt 提交、/history 轮询、/view 下载、mock 合成
- `backend/core/persistence/session_manager.py` — `SessionManager`：VIDEO_STEPS 序列、步骤结果/完成态/取消标志；新增 `save_aux_state`（辅助状态如 comfyui_import，复用 step_results 表不推进状态机）与 `rollback_completion`（回退完成态）
- `backend/core/services/step_payload.py` — `script_title`（列表展示剧本名）与 `video_step_results`（把工作区 markdown 投影回 step_results JSON 形状供 GET /sessions/{id} 返回，无 DB fallback，注入 comfyui_import）
- `backend/api/v1/settings.py` — ComfyUI 连接管理：GET/PUT /api/v1/settings/comfyui-connection（读写 `~/.claude/skills/comfyui-restart/hosts.json` 的 gz15-a100 条目、密码脱敏、杀旧隧道重启 start_comfyui_tunnel.sh、35s 轮询探测 127.0.0.1:8188 连通）
- `start_comfyui_tunnel.sh` — SSH 隧道：gz15-a100:8188 → 本地 127.0.0.1:8188（凭据复用 comfyui-restart skill 的 hosts.json，幂等断线自动重连，PID 文件管理）；start_all.sh 集成随主服务拉起
- `backend/deps.py` — `get_session_manager`（lru_cache，steps=VIDEO_STEPS）、`get_workflow`（**lru_cache 单例**，import 自 backend.core.workflows.video_workflow，注入 store）、`load_video_session`（统一 404）、`run_agent_endpoint`
- `frontend/src/pages/WorkflowPage.tsx` — 视频工作台页面（App.tsx 路由 `/`），组装 4 步组件
- `frontend/src/components/workflow/Step6Videos.tsx` — 步骤 4 前端（955 行，文件名为遗留命名）：分镜轨道选择、生成/取消/备份恢复、ComfyUI 导入、final_video + timeline_data 展示（LazyVideo）、usePolling 轮询
- `frontend/src/api/client.ts` — `sessionApi`（create/list/get/delete）与 `stepApi`（selectEpisode、importComfyUI（segmentIndexes+globalPrompt）、startComfyUIVideo、generateVideos（可选 segmentIndexes）、cancelVideos、restoreVideosBackup 等）
- `comfyUI-flow/`（未跟踪目录） — 第三方开源插件仓 ComfyUI-MiniMaxH3-TimelineDirector（MiniMax H3 无限时长分段长视频生成：分段续接 AV Latent、同种子、音画合并），本项目视频生成后端方案与工作流模板来源

## 关键逻辑说明

### 会话生命周期（backend/api/v1/sessions.py，挂载前缀 /api/v1/sessions）

| 路由 | 处理函数 | 行为 |
|------|---------|------|
| POST /sessions/from-script | create_session_from_script | 201 建视频会话；校验链：剧本会话不存在或 workflow_type≠script → 404；剧本会话 `episode_design` 未完成 → 400；分集不存在 → 404；WorkspaceStoreError → 400 |
| POST /sessions | create_session | 201 创建空视频会话（workflow_type 默认 "video"） |
| GET /sessions | list_sessions | 过滤掉 workflow_type=script 的会话；旧版 5/7 步会话标记 legacy=true（前端隐藏） |
| GET /sessions/{id} | get_session | 详情；step_results 经 `video_step_results` 工作区投影组装 |
| DELETE /sessions/{id} | delete_session | 删除会话 |

- from-script 创建：`session_manager.create_session(session_id, workflow_type="video", script_session_id=..., source_episode_id=...)`，session_id 为 uuid4；分集实体经 `get_workspace_store().get_episode(script_session_id, episode_id)` 读取（schema 层 `CreateVideoSessionFromScriptRequest`，episode_id 有 pattern 校验）。
- legacy 判定（list_sessions）：`bool(completed_steps) and (无 select_episode 结果 or 含旧步骤结果)`；同时从 select_episode 结果带出 script_session_id/script_title/episode_title/episode_number。

### 步骤 1：从剧本选集（POST /api/v1/steps/{session_id}/select-episode）

- 请求 `SelectEpisodeRequest`（backend/schemas/steps.py）：script_session_id、episode_id（pattern 校验）、resolution（默认 1080p，RESOLUTION_OPTIONS 现含 480p/720p/1080p/2k/4k）、aspect_ratio（默认 16:9）、max_segment_duration（5-30，默认 15）。
- API 层组装 `video_params` dict 调 `get_workflow().step_select_episode(...)`；失败（剧本会话不存在/分集设计未完成/分集不存在/VideoParams 校验失败）→ 400。
- `VideoCreationWorkflowV2.step_select_episode` 二次校验（兜底防串改）后保存 `select_episode` 步骤结果：`{script_session_id, episode_id, episode_title, video_params}`。`VideoParams(**video_params)` 负责参数合法性。
- 分集读取经 `get_selected_episode`（backend/core/services/workspace_sections.py，未完成抛 WorkflowError 含旧会话不兼容提示）。

### 步骤 4：生成视频（backend/api/v1/steps.py + video_workflow.py）

路由（生成/取消/恢复备份；**原 regenerate-videos 已并入 generateVideos 的指定段语义**）：

- **POST /{sid}/videos**：`can_execute_step(generate_videos)` 不过 → 400；无可用分镜数据 → 400；支持 `segmentIndexes` 可选参数（`_resolve_generation_segments`/`_configured_segment_indexes` 解析——不传=全部已配置分镜，传=仅指定段；前端分镜轨道 checkbox 连续勾选约束 + `splitContiguousRuns` 默认选最长连续段）；重新生成前 `mark_videos_generating` 为旧结果落备份（`_old_video_path`/`_backed_up_count`）；先落盘 pending 初始状态再提交后台任务，立即返回「任务已启动」。
- **POST /{sid}/cancel-videos**：无步骤结果或未在生成 → 400；写取消标志。
- **POST /{sid}/restore-videos-backup**：无视频数据 → 404；无可恢复备份 → 400；`restore_videos_backup` 把备份回填为当前结果。
- **POST /{sid}/import-comfyui**（「导入到 ComfyUI」）：`prepare_comfyui_import` → 后端照常上传素材 + 注入 timeline_data → **把注入后的 UI 版工作流写到服务器 `user/default/workflows/money-printer/导入_{会话ID}.json`**（`COMFYUI_WORKFLOW_UI_PATH` 为 UI 格式模板）；导入状态经 `session_manager.save_aux_state('comfyui_import')` 存 step_results 表（不推进状态机），`_get_imported_state` 读取；可带 `globalPrompt`（`_auto_global_prompt` 从容错提取全局提示词）。导入后由用户在 ComfyUI 侧手动执行，后端 `_execute_imported_videos` 承接后续状态。

- 生成主链路：`_collect_generation_materials` 收集素材（参考素材图 = 分镜 reference_images，http(s) 外链跳过不上传；音频 = session_assets；extra_prompt 并入 content）→ `comfyui_service.generate_full_video(segments, frame_image_paths, audio_assets, overlap_seconds, reference_image_paths)` → 成功落盘 `generate_videos` 结果：`generated_videos`（按 timeline 分段逐段记录 duration=(endFrame-startFrame)/fps）、`final_video`（video_path/prompt_id/mock/overlap_seconds/segment_count）、`timeline_data`、`_success: True`，并 update_session_status("completed")；异常落盘失败快照。
- `_get_video_segments` 取分镜：`store.read_storyboard(script_session_id, episode_id, session_id)` 读工作区分镜文件，映射为 `{index, content: prompt||outline, duration: max_segment_duration(默认15), reference_images}`。

### ComfyUI 整段生成（backend/core/services/comfyui_service.py，详见 ComfyUI 逻辑文档）

- `TimelineBuilder.build` 构造 timeline_data（version 5，fps=24）：段长对齐 `5+17n` 帧（上限 3592），段间 overlap 为 0 或 `5+17n` 帧，每段参考图 ≤9、参考音频 ≤3；`TimelineBuilder.validate` 校验不通过抛 ValueError。
- mock 模式（`COMFYUI_MOCK` 默认 true）：跳过 HTTP，OpenCV 本地合成演示视频（分段着色 + 段号/提示词文字 + overlap 渐变）。
- 真实链路：POST /upload/image 上传素材 → 上传名重建 timeline → 注入工作流模板（`COMFYUI_WORKFLOW_PATH` 现指向 `comfyUI-flow/ComfyUI-MiniMaxH3-TimelineDirector/example_workflows/` 下 *_api.json；另有 `COMFYUI_WORKFLOW_UI_PATH` UI 版模板供「导入到 ComfyUI」）→ POST /prompt 提交 → GET /history/{prompt_id} 轮询（默认 1800s 超时、5s 间隔）→ GET /view 下载到 `static/videos`。
- **部署体系**：远程 ComfyUI（gz15-a100 GPU 主机）经 SSH 隧道映射到本地 127.0.0.1:8188（start_comfyui_tunnel.sh）；连接信息可在前端 MainLayout 顶栏 ComfyUIConnectionModal 查看/更新（走 settings API，密码脱敏）。

### 前端（WorkflowPage + Step6Videos，2026-09-21 重构 955 行）

- 路由 `/` → WorkflowPage.tsx；步骤 4 组件 `frontend/src/components/workflow/Step6Videos.tsx`（**遗留文件名**，实际是第 4 步「视频」；StepNavigator.tsx:10-15 明确 4 步）。
- **分镜轨道** `renderTrain`：叠层卡片（-24px 负 margin 重叠表现 overlap）；checkbox 连续勾选约束（不可跳选）；未配置分镜渲染虚线占位块；`longestRun`/`splitContiguousRuns` 工具默认选最长连续段。
- **流程按钮**：`handleImport`（stepApi.importComfyUI，可带 globalPrompt）→ `handleGenerate`（startComfyUIVideo，可带 segmentIndexes）→ `handleCancel`（cancelVideos）；`handleRestoreBackup`（restoreVideosBackup，hasBackup 基于 `_backed_up_count`/`_old_video_path`）。
- **展示**：分镜详情 Modal、`final_video`（LazyVideo 懒加载）、`timeline_data` 分段表、视频预览时长计算。
- 轮询：`usePolling(refreshSession, { interval: 3000, enabled: ..., maxPolls, onMaxPolls })`——生成结束后有限次兜底刷新自动收尾。

## 依赖与复用关系

- 依赖: FastAPI BackgroundTasks（步骤 4 后台生成）、backend/deps.py 依赖注入（get_session_manager/get_workflow/get_storyboard_workflow/load_video_session）、SessionManager（SQLite data/sessions.db，VIDEO_STEPS 步骤状态机 + save_aux_state）、WorkspaceStore（分集/分镜 markdown 读取）、step_payload（step_results 投影）、VideoServiceComfyUI（整段视频生成）、settings API + start_comfyui_tunnel.sh（隧道运维）、前端 antd、axios、usePolling/LazyVideo
- 被依赖: 剧本工作流（script 链）完成 episode_design 后经 POST /sessions/from-script 进入本工作流；分镜工作流（storyboard.py）共享同一视频 SessionManager 单例承接步骤 2/3
- 可复用组件: SessionManager 步骤状态机（can_execute_step/reset_current_step，script/video 两链共用）；save_aux_state（任何「辅助状态不推进状态机」场景）；run_agent_endpoint 统一 agent 异步运行提交

## 注意事项

- **COMFYUI_MOCK 默认开启**：backend/core/config.py 默认 "true"，即默认走本地 OpenCV 演示视频；真实链路需 COMFYUI_MOCK=false 且隧道/远程 ComfyUI 可达。
- **工作流模板来源**：`COMFYUI_WORKFLOW_PATH` 指向 comfyUI-flow/（未跟踪目录，需本地存在该插件仓）；模板缺失时真实链路 `load_workflow_template` 会抛 FileNotFoundError。
- **overlap 语义**：选集请求不含 overlap_seconds（生成时从 video_params dict 取，未写入则恒为 0）；分镜级 overlap 存于 StoryboardSegment.overlap（0-3，仅全能参考模式）。
- **导入到 ComfyUI 与生成的分野**：导入只负责「素材上传 + timeline 注入 + UI 工作流落盘」，生成执行在 ComfyUI 侧手动触发；导入状态为辅助状态（save_aux_state），不改变步骤状态机。
- **备份恢复**：重新生成前旧结果自动备份，restore-videos-backup 可回滚；恢复的时长语义以实现为准。
- **legacy 会话兼容**：列表接口把无 select_episode 或含旧步骤结果的会话标 legacy，前端隐藏。
- **取消不中断已提交任务**：cancel-videos 写取消标志；已提交到 ComfyUI 的任务不主动撤回（前端按钮仍可用，属已知待完善点）。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析生成（feat/create_story 分支工作区状态） |
| 2026-09-21 | 同步重构 — 生成链迁至 backend/core/workflows/video_workflow.py（617 行）；新增指定段生成（segmentIndexes + 分镜轨道连续勾选）、备份恢复（mark_videos_generating/restore_videos_backup）、「导入到 ComfyUI」（UI 工作流写服务器 + save_aux_state）、_auto_global_prompt；COMFYUI_WORKFLOW_PATH 改指 comfyUI-flow/（MiniMax H3 TimelineDirector）+ 新增 COMFYUI_WORKFLOW_UI_PATH + RESOLUTION_OPTIONS 加 480p；新增 settings API 与 SSH 隧道体系（start_comfyui_tunnel.sh）；deps.get_workflow 改 lru_cache 单例；前端 Step6Videos 重构（955 行）；删除 regenerateVideos/regenerateSingleVideo 前端 API |