---
name: 视频创作工作流（视频会话与生成）
摘要: 视频 4 步工作流（选集/分镜大纲/分镜管理/生成视频）：POST /api/v1/sessions/from-script 从剧本建会话，步骤 API 驱动 StoryboardWorkflow 与 VideoCreationWorkflowV2，最终 ComfyUI 整段时间轴生成视频（mock 兜底），支持取消/重生成/备份恢复。
tags: 后端API, 视频生成, ComfyUI, 会话管理, 前端页面
---

# 视频创作工作流（视频会话与生成）

**状态:** 已完成
**最后更新:** 2026-09-19

## 功能概述

剧本创作工作流（script 链）的下游视频生产链：从已完成的剧本会话选一个分集创建视频会话，按 4 步流水线产出最终视频。

4 步序列（`VIDEO_STEPS`，定义于 backend/core/persistence/session_manager.py:22）：

1. `select_episode` — 从剧本选集，绑定分集设计与视频参数（resolution/aspect_ratio/max_segment_duration）
2. `storyboard_outline` — 分镜大纲（agent 生成导图 + 分镜列表，人工编辑 reconcile）
3. `segment_management` — 分镜管理（分镜形式/overlap 配置、参考素材图、提示词生成）
4. `generate_videos` — 视频生成（远程 ComfyUI 整段时间轴一次生成整条视频，mock 本地兜底）

步骤 2/3 的分镜侧逻辑由 StoryboardWorkflow（backend/core/agents/storyboard.py）承担，详见分镜工作流文档；本文聚焦视频会话生命周期与步骤 1/4。

整体数据流：前端 WorkflowPage（路由 `/`）→ stepApi/sessionApi（frontend/src/api/client.ts，baseURL `/api/v1`）→ backend/api/v1/sessions.py + backend/api/v1/steps.py（backend/main.py:77-78 挂载 `/api/v1/sessions`、`/api/v1/steps`）→ VideoCreationWorkflowV2 / StoryboardWorkflow → SessionManager（SQLite data/sessions.db）+ WorkspaceStore（workspace/ markdown 权威源）→ VideoServiceComfyUI（backend/core/services/comfyui_service.py）。

## 核心代码路径

- `backend/api/v1/sessions.py` — 视频会话 CRUD：POST /from-script 从剧本建会话、GET 列表（legacy 会话标记、剧本会话过滤）、GET 详情（工作区投影 step_results）、DELETE
- `backend/api/v1/steps.py` — 视频 4 步工作流全部步骤端点；步骤 4 的生成/取消/重生成/恢复备份 4 条路由与初始状态构建（`_build_initial_videos` 等）在本文件
- `backend/core/agents/workflow_v2.py` — `VideoCreationWorkflowV2`：step_select_episode（选集绑定 video_params）、`_get_video_segments`（legacy 兜底 + 读工作区分镜）、`step_generate_videos`（ComfyUI 整段生成主链路）
- `backend/core/agents/storyboard.py` — `StoryboardWorkflow`：步骤 2/3 的分镜大纲生成/编辑、分镜配置、素材池、提示词生成（本文不展开）
- `backend/core/models/video_models.py` — 领域模型：`VideoParams`（分辨率/宽高比/最大分片时长 5-30s/overlap 0-5s）、`StoryboardSegment`、`SegmentReferenceImage`
- `backend/core/services/comfyui_service.py` — `VideoServiceComfyUI`/`TimelineBuilder`/`ComfyUIClient`：timeline_data 构造与校验、素材上传、/prompt 提交、/history 轮询、/view 下载、mock 合成
- `backend/core/persistence/session_manager.py` — `SessionManager`：VIDEO_STEPS 序列、步骤结果/完成态/取消标志/会话资产管理
- `backend/core/services/workspace_projection.py` — `script_title`（列表展示剧本名）与 `video_step_results`（把工作区 markdown 投影回旧 step_results JSON 形状供 GET /sessions/{id} 返回）
- `backend/deps.py` — `get_session_manager`（lru_cache，steps=VIDEO_STEPS）、`get_workflow`（非缓存，每次新建 VideoCreationWorkflowV2 但共享单例 SessionManager）、`load_video_session`（统一 404）、`start_agent_run`（统一 run_id 响应）
- `frontend/src/pages/WorkflowPage.tsx` — 视频工作台页面（App.tsx 路由 `/`），组装 4 步组件
- `frontend/src/components/workflow/Step6Videos.tsx` — 步骤 4 前端：生成/停止/重新生成/恢复备份按钮、final_video + timeline_data + mock 标记展示（LazyVideo）、3 秒轮询
- `frontend/src/api/client.ts` — `sessionApi`（create/list/get/delete）与 `stepApi`（selectEpisode、videos、regenerateVideos、cancelVideos、restoreVideosBackup 等）

## 关键逻辑说明

### 会话生命周期（backend/api/v1/sessions.py，挂载前缀 /api/v1/sessions）

| 路由 | 处理函数 | 行为 |
|------|---------|------|
| POST /sessions/from-script | create_session_from_script | 201 建视频会话；校验链：剧本会话不存在或 workflow_type≠script → 404；剧本会话 `episode_design` 未完成 → 400；分集不存在 → 404；WorkspaceStoreError → 400 |
| POST /sessions | create_session | 201 创建空视频会话（workflow_type 默认 "video"） |
| GET /sessions | list_sessions | 过滤掉 workflow_type=script 的会话；旧版 5/7 步会话标记 legacy=true（前端隐藏） |
| GET /sessions/{id} | get_session | 详情；step_results 经 `video_step_results` 工作区投影组装 |
| DELETE /sessions/{id} | delete_session | 删除会话 |

- from-script 创建：`session_manager.create_session(session_id, workflow_type="video", script_session_id=..., source_episode_id=...)`，session_id 为 uuid4；分集实体经 `get_workspace_store().get_episode(script_session_id, episode_id)` 读取（schema 层 `CreateVideoSessionFromScriptRequest`，backend/schemas/script.py:93，episode_id 有 pattern 校验）。
- legacy 判定（list_sessions）：`bool(completed_steps) and (无 select_episode 结果 or 含 generate_segment_scripts / generate_episode_reference_images / generate_segment_frames 任一旧步骤结果)`；同时从 select_episode 结果带出 script_session_id/script_title/episode_title/episode_number（`_episode_number` 用正则 `^ep_(\d+)$` 解析集数）。

### 步骤 1：从剧本选集（POST /api/v1/steps/{session_id}/select-episode）

- 请求 `SelectEpisodeRequest`（backend/schemas/steps.py:10）：script_session_id、episode_id（pattern 校验）、resolution（默认 1080p）、aspect_ratio（默认 16:9）、max_segment_duration（5-30，默认 15）。注意：请求不含 overlap_seconds，该值由分镜配置阶段按分镜设置。
- API 层组装 `video_params` dict 调 `get_workflow().step_select_episode(...)`；失败（剧本会话不存在/分集设计未完成/分集不存在/VideoParams 校验失败）→ 400。
- `VideoCreationWorkflowV2.step_select_episode`（workflow_v2.py:62）二次校验（兜底防串改）后保存 `select_episode` 步骤结果：`{script_session_id, episode_id, episode_title, video_params}`。`VideoParams(**video_params)`（backend/core/models/video_models.py:5）负责参数合法性（max_segment_duration 5-30、overlap_seconds 0-5）。
- `get_selected_episode` 读取该绑定；旧会话无此步骤结果时抛 ValueError（「请从『创作剧本』重新开始」）。

### 步骤 4：生成视频（backend/api/v1/steps.py:211-409 + workflow_v2.py:166-299）

四条路由：

| 路由 | 行为 |
|------|------|
| POST /{sid}/videos | `can_execute_step(generate_videos)` 不过 → 400；`workflow._get_video_segments` 为空 → 400（无可用分镜数据）；先落盘 pending 初始状态（`_generating: True, _success: False`），再 `BackgroundTasks.add_task` 提交后台任务，立即返回「任务已启动」 |
| POST /{sid}/cancel-videos | 无步骤结果或 `_generating` 非 True → 400；`set_step_cancelled` 写 `result_data['_cancelled']=True` |
| POST /{sid}/regenerate-videos | 要求 generate_videos 与 segment_management 均已完成（否则 400）；`reset_current_step` 重置后，`_build_initial_videos(segments, existing_videos)` 为每个分镜保留 `_old_video_path`/`_old_video_id` 备份字段再重新生成 |
| POST /{sid}/restore-videos-backup | 无视频数据 → 404；无可恢复备份 → 400；把 `_old_video_path` 回填为 `video_path`、`task_status='completed'`、`duration=5.0`（恢复默认时长），重算 success/failed_count 后落盘（success=True） |

- 后台任务执行：`_submit_video_background_task` 用 `asyncio.run(execute_step())` 包装 `get_workflow().step_generate_videos(session_id)`（进度落盘由 workflow 负责，前端轮询读取）。
- `step_generate_videos` → `_step_generate_videos_comfyui`（workflow_v2.py:190）材料收集：
  - 首帧：读旧步骤 `generate_segment_frames` 结果的 `first_image_path`（新会话通常无，缺失分片不传参考图）；
  - 参考素材图：`_get_video_segments` 带出的 `reference_images`（全能参考模式），http(s) 外链跳过不上传；
  - 音频：`session_manager.list_assets(session_id, asset_type="audio")`；
  - `extra_prompt` 若存在则并入每段 content。
- 调 `comfyui_service.generate_full_video(segments, frame_image_paths, audio_assets, overlap_seconds, reference_image_paths)`，成功后落盘 `generate_videos` 结果：`generated_videos`（按 timeline 分段逐段记录 duration=(endFrame-startFrame)/fps）、`final_video`（video_path/prompt_id/mock/overlap_seconds/segment_count）、`timeline_data`、`_success: True`，并 `update_session_status(session_id, "completed")`；异常时落盘失败快照（failed_count=1、error 信息，success=False）。
- `_get_video_segments`（workflow_v2.py:119）取分镜的顺序：优先旧 `generate_segment_scripts` 步骤结果（legacy 会话兜底）；否则 `store.read_storyboard(script_session_id, episode_id, session_id)` 读工作区分镜文件，映射为 `{index, content: prompt||outline, duration: max_segment_duration(默认15), reference_images}`。

### ComfyUI 整段生成（backend/core/services/comfyui_service.py，详见 ComfyUI 逻辑文档）

- `TimelineBuilder.build` 构造 timeline_data（version 5，fps=24）：段长对齐 `5+17n` 帧（上限 3592），段间 overlap 为 0 或 `5+17n` 帧，每段参考图 ≤9、参考音频 ≤3；`TimelineBuilder.validate` 校验不通过抛 ValueError。
- mock 模式（`COMFYUI_MOCK` 默认 true，backend/core/config.py:29）：跳过 HTTP，OpenCV 本地合成演示视频（分段着色 + 段号/提示词文字 + overlap 渐变）。
- 真实链路：POST /upload/image 上传素材 → 上传名重建 timeline → 注入工作流模板（`COMFYUI_WORKFLOW_PATH`，config.py:31，指向 backend/comfyui_workflow.json）→ POST /prompt 提交 → GET /history/{prompt_id} 轮询（默认 1800s 超时、5s 间隔）→ GET /view 下载到 `static/videos`（`VIDEO_SAVE_DIR`，backend/core/utils/path_utils.py:5）。

### 前端（WorkflowPage + Step6Videos）

- 路由 `/` → WorkflowPage.tsx（frontend/src/App.tsx:18）；步骤 4 组件 `frontend/src/components/workflow/Step6Videos.tsx`。
- `canExecute`：`completed_steps` 含 `segment_management`；生成中判定 = 存在 pending 视频 || `stepResult._generating === true` || 本地 loading。
- 轮询：`usePolling(refreshSession, { interval: 3000, enabled: pending || _generating })`（frontend/src/hooks/usePolling.ts），每 3 秒刷会话详情读后台进度。
- 展示：`final_video`（video_path + mock 标记，LazyVideo 懒加载播放）、`timeline_data` 分段表、备份恢复/重新生成/停止按钮；调用 stepApi 的 `generateVideos/regenerateVideos/cancelVideos/restoreVideosBackup`（client.ts:179-198 一带）。

## 依赖与复用关系

- 依赖: FastAPI BackgroundTasks（步骤 4 后台生成）、backend/deps.py 依赖注入（get_session_manager/get_workflow/get_storyboard_workflow/load_video_session/start_agent_run）、SessionManager（SQLite data/sessions.db，VIDEO_STEPS 步骤状态机）、WorkspaceStore（分集/分镜 markdown 读取）、workspace_projection（step_results 投影）、VideoServiceComfyUI（整段视频生成）、前端 antd、axios、usePolling/LazyVideo
- 被依赖: 剧本工作流（script 链）完成 episode_design 后经 POST /sessions/from-script 进入本工作流；分镜工作流（storyboard.py）共享同一视频 SessionManager 单例承接步骤 2/3
- 可复用组件: SessionManager 步骤状态机（can_execute_step/reset_current_step/set_step_cancelled，script/video 两链共用）；start_agent_run 统一 agent 异步运行提交

## 注意事项

- **取消标志当前无消费方**：cancel-videos 只写 `result_data['_cancelled']=True`（session_manager.set_step_cancelled）；`is_step_cancelled` 在 backend 内无调用点，`_step_generate_videos_comfyui` 生成循环不检查该标志，取消不会中断已提交的 ComfyUI 任务（前端按钮仍可用，属已知待完善点）。
- **COMFYUI_MOCK 默认开启**：backend/core/config.py:29 默认 "true"，即默认走本地 OpenCV 演示视频；真实链路需 COMFYUI_MOCK=false 且远程 ComfyUI 可达。
- **工作流模板文件缺失**：`COMFYUI_WORKFLOW_PATH = BASE_DIR / "comfyui_workflow.json"`（BASE_DIR 为 backend/ 目录），该文件当前在仓库中不存在；mock 模式不需要，真实链路 `load_workflow_template` 会抛 FileNotFoundError。
- **步骤 4 不含 overlap_seconds 入参**：选集请求只绑定 resolution/aspect_ratio/max_segment_duration；生成时 `overlap_seconds` 从 `video_params` dict 取（`params.get('overlap_seconds', 0)`，选集未写入则恒为 0），分镜级 overlap 存于 StoryboardSegment.overlap（0-3，仅全能参考模式）。
- **旧编号残留**：workflow_v2.py 的 `step_generate_videos` docstring 仍写「步骤7」（历史 7 步流程遗留），实际是 4 步流程的步骤 4。
- **POST /sessions/from-script 前端未见调用方**：frontend/src 中未 grep 到 "from-script" 调用，sessionApi.create 仅 POST /sessions（空会话）；该端点目前为后端能力（前端入口待接入或经其他途径调用）。
- **legacy 会话兼容**：列表接口把无 select_episode 或含旧步骤结果的会话标 legacy，前端隐藏；`_get_video_segments` 优先读旧 `generate_segment_scripts` 结果兜底旧会话视频生成。
- **备份恢复时长失真**：restore-videos-backup 将恢复的视频 duration 统一置 5.0（代码注释「恢复默认时长」），非原视频真实时长。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析生成（feat/create_story 分支工作区状态） |
