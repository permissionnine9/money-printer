---
name: 项目概述
摘要: AI 剧本/视频创作平台：双 4 步工作流，FastAPI + React 19 前后端分离，claude-agent-sdk 编排 LLM，markdown 权威源 + SQLite 会话状态。
tags: overview, architecture, constraints
---

# 项目概述

**最后更新:** 2026-09-19

## 概述

money-printer 是一个 AI 剧本/视频创作平台。前端 React 19 + AntD 6 + zustand，后端 FastAPI（uv 管理 Python >= 3.11）。业务上为双 4 步工作流：

- **剧本链**：故事构思 ideation 对话/定稿 → 大纲 → 分集设计+实体库 → 定妆照 lookbook
- **视频链**：从剧本选集 → 分镜大纲 → 分镜管理/素材/prompt → ComfyUI 视频生成

后端入口 `backend/main.py` 创建 FastAPI（title='AI视频创作智能体 API', version='2.0.0', lifespan）：
- lifespan 启动时调 `backend/config.py` 的 `override_src_config()` 打印模型管理默认模型
- CORS 允许 http://localhost:5173 与 :3000；`app.mount('/static', StaticFiles(directory='static'))` 提供图片/视频静态资源
- 全局 exception_handler 将 ScriptWorkflowError/StoryboardError 转 HTTP（status_code 取异常携带值，默认 400）
- include_router 8 个模块（sessions/steps/uploads/assets/models/prompts/script_sessions/agent_runs），均挂 `/api/v1/*` 前缀；GET `/` 与 `/health` 健康检查；`__main__` 下 uvicorn 0.0.0.0:8000 reload

LLM 编排用 claude-agent-sdk 0.2.154（ClaudeSDKClient 子进程驱动本机 Claude Code CLI）；生成内容以 `workspace/` frontmatter markdown 为权威源，会话/任务状态存 SQLite `data/sessions.db`。

前端路由（`frontend/src/App.tsx`）：main.tsx 用 BrowserRouter → App.tsx 内 MainLayout 包 Routes：`/script` → ScriptWorkflowPage（剧本 4 步）、`/` → WorkflowPage（视频 4 步）、`/models` → ModelsPage（image/chat/agent 模型配置 CRUD）、`/prompts` → PromptsPage（backend/prompts markdown 模板编辑）。MainLayout 含顶导航 + SessionSider 会话侧栏（视频会话按引用剧本二级分组）。

## 项目目标

- 剧本链 4 步闭环（SCRIPT_STEPS：story_ideation → story_outline → episode_design → lookbook_images）：产出含 conflict_chain/causality_chain/ending_summary(100-300字)/story_progress(≤600字)/clue_refs/foreshadow_refs 的分集、前缀 chr_/scn_/clu_/fs_ 的实体库（description ≤80 字供生图）、以及定妆照（lb_* 任务状态机 pending→completed）
- 视频链 4 步闭环（VIDEO_STEPS：select_episode → storyboard_outline → segment_management → generate_videos）：从剧本选集 → 分镜大纲 → 分镜管理/素材/prompt → ComfyUI 视频生成；timeline version=5、fps=24、段长对齐 5+17n 帧、每段 ≤9 图 ≤3 音频；产物下载到 `static/videos/`
- 所有 LLM 生成内容以 `workspace/` frontmatter markdown 为权威源；会话/任务状态存 SQLite `data/sessions.db`（WAL）
- 用户可自助管理 image/chat/agent 三类模型默认配置与 backend/prompts markdown 模板
- 提示词透明化：agent 发起调用前流出 prompt 事件（含最终 system/user prompt 与模型名）；成本可观测（AgentRunResult 含 usage/cost_usd）
- 业务量化目标（KPI）：（待补充）

## 项目架构

- **backend/main.py** — 职责: FastAPI 入口（lifespan 启动打印默认模型、CORS、/static 静态资源、全局异常转换、挂载 8 个 `/api/v1/*` router、/ 与 /health 健康检查、uvicorn 启动），依赖: backend/config.py（override_src_config）、backend/api/v1/ 各 router
- **backend/api/v1/** — 职责: 8 个 router。sessions：视频会话 CRUD + POST /from-script(201)；steps：视频步骤面（select-episode、storyboard-outline generate(PUT 更新)、segments/{i}/config、material-pool、segments/{i}/reference-images、generate-material、prompt-context、generate-prompt、segment-management/complete、videos / cancel-videos / regenerate-videos / restore-videos-backup）；script_sessions：会话 CRUD + ideation/message|finalize（POST SSE 直跑）+ GET/PUT ideation + outline generate/get/put + episodes generate/regenerate/CRUD + entities CRUD + entities/{id}/references + lookbook generate/complete/list/{imageId}/regenerate|delete；agent_runs：GET /{run_id}/events?seq=（SSE 观流）、GET /{run_id}（轮询兜底）、POST /{run_id}/cancel；models/prompts/uploads(/image)/assets CRUD，依赖: backend/deps.py 提供的单例
- **backend/deps.py** — 职责: lru_cache 单例依赖注入。get_session_manager()=SessionManager(steps=VIDEO_STEPS)、get_script_session_manager()=SessionManager(steps=SCRIPT_STEPS)（双 4 步参数化）、get_script_manager()=ScriptManager、get_model_manager()=ModelManager（共用同一 SQLite）、get_workspace_store()=WorkspaceStore（markdown 权威源）、get_storyboard_workflow()=StoryboardWorkflow（共享视频 SessionManager + WorkspaceStore）；get_workflow()（非缓存）返回 VideoCreationWorkflowV2；load_video_session/load_script_session 校验；start_agent_run(label, factory) 统一 `{'success':True,'data':{'run_id':...}}` 响应，依赖: SessionManager/ScriptManager/ModelManager/WorkspaceStore/StoryboardWorkflow/VideoCreationWorkflowV2、get_run_registry()
- **backend/core/agent_sdk/** — 职责: claude-agent-sdk 封装。wrapper.run_agent/run_conversation（AgentRunOptions：prompt/system_prompt/max_turns=40/tools 默认只读白名单 READ_ONLY_TOOLS=[Read,Grep,Glob]/mcp_servers/cwd 锁定剧本工作区/resume 多轮/interrupt/output_format JSON Schema/env；permission_mode=bypassPermissions、setting_sources=[]、include_partial_messages=True、max_thinking_tokens=6000）；model_env.build_agent_env() 注入 ANTHROPIC_* 环境变量（CLAUDE_AGENT_SDK_CLIENT_APP=money-printer/2.0）；registry.AgentRunRegistry 进程内单例（run_id 12 位 hex、events deque maxlen=5000 带 seq、MAX_RUNS=200、asyncio.Condition 驱动）；events.py 事件归一（type ∈ thinking/text_delta/tool_use/tool_result/result/error/prompt，to_sse 输出 data 行），依赖: claude-agent-sdk 0.2.154、ModelManager.get_default_model('agent')
- **backend/core/agents/** — 职责: `script_workflow.py`（剧本链：ideation 多轮盘问 resume 复用 agent session + finalize 收敛、大纲 markmap JSON 导图、分集设计经进程内 MCP server（create_sdk_mcp_server 'script_design' v1.0.0）注册 upsert_character/scene/clue/foreshadow + save_episode 写侧工具直接调 WorkspaceStore/ScriptManager 落盘、定妆照 agent 出英文 prompt）；`storyboard.py`（分镜大纲 agent 检索工作区出 JSON 导图+segments、人工编辑导图解析同步 reconcile、分镜 mode/overlap 配置、参考素材图池、AI 生成素材图、分镜提示词生成）；`workflow_v2.py`（VideoCreationWorkflowV2.generate_videos 视频生成链），依赖: backend/core/agent_sdk/、backend/core/persistence/workspace_store.py、ScriptManager、ImageService、ScriptContextService、TimelineBuilder、ComfyUI service
- **backend/core/services/** — 职责: `comfyui_service.py`（含 TimelineBuilder：真实链路 httpx POST /upload/image 上传素材 → 注入 workflow 模板 → POST /prompt → 轮询 GET /history/{id} → GET /view 下载；COMFYUI_MOCK=true 时本地 OpenCV 合成演示 mp4）；`image_service.py`（OpenAI 兼容协议 POST {base_url}/images/generations 与 /images/edits（参考图上限 4 张），404/429/5xx 重试 3 次、b64_json 落盘 static/images/、archive_generated_image 归档、build_image_service_from_model_config 构造）；`video_prompt_skill.py`（video-prompt skill 同步进 story 工作区 99-references/ 供 agent Read，渐进式披露）；`workspace_projection.py`（旧形状投影回 step_results JSON）；OSSService（oss_service.py，boto3 S3 兼容、3 次重试）与 http_utils.download_to_file 均无调用方（预留/遗留未定），依赖: backend/core/config.py 常量、模型管理 image 类型默认配置
- **backend/core/persistence/** — 职责: `workspace_store.py`（workspace/ frontmatter markdown 权威源：原子写 tmp+os.replace、per-story RLock、实体 ID 全局分配锁、ID 正则白名单（ep_[0-9]{2,}、(chr|scn|clu|fs)_[0-9]{3,}）防 glob 注入/路径穿越、## 标题转义往返、MAP.md 自动渲染）；`base.py`（BaseSQLiteManager，WAL，数据库路径 data/sessions.db 硬编码于此）；`session_manager.py`（SCRIPT_STEPS/VIDEO_STEPS 定义与步骤状态机）、`script_manager.py`（episodes/script_entities/lookbook_images/episode_material_images DAO），依赖: SQLite 表 sessions/step_results/session_assets/script_entities/episodes/lookbook_images/episode_material_images/image_models
- **backend/core/models/video_models.py** — 职责: StoryboardSegment（index 0 起、title、outline 80-150 字、mode ∈ first_frame/last_frame/all_reference/first_last_frame 默认 all_reference、overlap 0-3 默认 1 且首镜固定 0、duration 5-30s 默认 15、prompt、reference_images）与 VideoParams（resolution='1080p'、aspect_ratio='16:9'、max_segment_duration=15(5-30)、overlap_seconds=0.0(0-5)、to_prompt_context()）pydantic 模型；仅 all_reference 模式实现 overlap/提示词生成逻辑（video_models 字段描述与 storyboard.py 注释一致，其余三模式关联逻辑未实现）
- **backend/core/config.py** — 职责: 配置常量（backend/.env load_dotenv override=True 覆盖）：COMFYUI_BASE_URL 默认 http://127.0.0.1:8188、COMFYUI_MOCK 默认 true、COMFYUI_WORKFLOW_PATH=backend/comfyui_workflow.json（模板文件未入库，真实链路需自备）、COMFYUI_TIMELINE_FPS=24、OSS_ACCESS_KEY/SECRET_KEY/BUCKET 默认空、OSS_ENDPOINT 默认 http://oss-cn-guangzhou.aliyuncs.com、OSS_REGION 默认 cn-guangzhou
- **frontend/src/** — 职责: React 19 + AntD 6 + zustand 前端。两层 API：axios baseURL /api/v1 做 CRUD/触发 + `frontend/src/api/sse.ts` 原生 fetch+ReadableStream 手写 SSE 解析（未用 EventSource，POST 直跑与 GET 观流共用同一实现）；断线重连逻辑在 `AgentRunProgress.tsx`（MAX_RETRIES=6 × RETRY_INTERVAL=2000ms，按 lastSeq 增量续传+赋值幂等去重）；AgentRunProgress（thinking/text 流式、取消 run）、PromptViewerModal（查看最终提示词）、MindmapView（markmap-lib/view，尺寸 0 时 ResizeObserver 延迟渲染）、LazyVideo（IntersectionObserver 懒加载）、scriptMarkdown.ts（拼装完整剧本 Blob 下载）、MentionImageInput（@图片引用输入）；无 localStorage/持久层，会话恢复靠 URL ?session_id=；已知 markdown-it 被 StepEpisodeDesign.tsx 直接 import 但未声明在 package.json dependencies（靠 markmap-lib 传递依赖，依赖漂移风险），依赖: vite dev 代理 /api 与 /static → http://localhost:8000（dev 端口 5173 host 0.0.0.0）
- **backend/scripts/migrate_db_to_workspace.py** — 职责: SQLite → workspace 迁移 CLI（argparse --export/--verify/--cutover/--purge-tables；--export 幂等导出；--verify 双向对账忽略时间戳/edited，差异非零退出；--cutover 前置检查 → shutil.copy2 备份 DB（sessions.db.bak-YYYYmmdd-HHMMSS）→ 内容行替换薄 envelope → 可选 DELETE episodes/script_entities、永不 DROP 表；cutover 后自动停用 export/verify）
- **tests/manual/** — 职责: 三个非 pytest 手动脚本（__main__ 直接跑）：test_agent_sdk.py（SDK 流式/resume/interrupt/MCP 验证）、test_phase1_data.py（SessionManager 步骤状态机、ScriptManager DAO、实体全局 ID 分配 SELECT MAX+1 删除回退复用）、test_workspace_store.py（文件化 CRUD、路径穿越封堵白名单正则、标题转义双射、8 线程并发原子写、跨会话 ID 隔离、级联清理 delete_story_content/delete_story）
- **workspace/、data/、static/** — 职责: 存储层。`workspace/{剧名}-{sid8}/` story 树 = MAP.md + 00-ideation/ + 01-outline/ + 02-episodes/ + 03-entities/ + 04-storyboards/{ep_xx}/vs-{视频会话id前8位}/（同分集多次视频会话=兄弟 vs 目录）+ 99-references/（video-prompt skill 同步目录）；`data/sessions.db` 会话/任务状态（sessions 表：session_id PK、workflow_type 'video'|'script'、current_step、status active/completed/error、workspace_path、script_session_id、source_episode_id；step_results 为薄 envelope {_artifact:'workspace',path}）；`static/images/`、`static/videos/` 生成产物

## 设计原则

| 决策 | 理由 | 日期 |
|------|------|------|
| 生成内容文件化：workspace/ frontmatter markdown 为权威源，SQLite step_results 仅薄 envelope {_artifact:'workspace',path} | 生成内容可读可编辑、迁移脚本可双向对账（--verify）；会话/任务状态仍由 SQLite（WAL）承担，读旧形状经 workspace_projection.py 投影 | 2026-09-19 |
| LLM 编排用 claude-agent-sdk 0.2.154 子进程驱动本机 Claude Code CLI | ClaudeSDKClient 支持 resume 多轮、output_format JSON Schema 结构化输出、interrupt 取消；默认只读白名单 READ_ONLY_TOOLS=[Read,Grep,Glob]，写侧统一收敛到进程内 MCP server 写侧工具直接落盘 | 2026-09-19 |
| 长任务统一 run_id 异步模型 | POST 即返 run_id（AgentRunRegistry 进程内单例：events deque maxlen=5000 带 seq、MAX_RUNS=200），SSE 按 seq 回放+实时（asyncio.Condition 驱动），GET 轮询兜底，取消经 interrupt_event→client.interrupt() | 2026-09-19 |
| workspace 原子写 + 多级锁 + ID 白名单 | tmp+os.replace 原子写、per-story RLock、实体 ID 全局分配锁、ID 正则白名单防 glob 注入/路径穿越；8 线程并发原子写有 tests/manual/test_workspace_store.py 覆盖 | 2026-09-19 |
| COMFYUI_MOCK 默认 true | 无 ComfyUI 环境时本地 OpenCV 合成演示 mp4，保证视频链路端到端可演示 | 2026-09-19 |
| 双 4 步参数化 SessionManager | get_session_manager()/get_script_session_manager() 以 steps=VIDEO_STEPS/SCRIPT_STEPS 参数化复用同一状态机（推进/回退/can_execute_step 前置校验/clear_steps_after 清下游/_cancelled 取消标志） | 2026-09-19 |
| 前端 4 步子组件 display:none keep-alive 不卸载 | 切换步骤时保 SSE/轮询不断 | 2026-09-19 |
| （待补充） | 更多原则请通过 /harness-update 补充 | - |

## 不可违背的核心逻辑

- **禁止** 未配置模型管理 agent 类型默认模型即发起 agent 调用 — model_env.build_agent_env() 从 ModelManager.get_default_model('agent') 读 base_url/api_key/model_id 注入 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN+ANTHROPIC_API_KEY（双注入）/ANTHROPIC_MODEL，未配置抛 AgentModelNotConfiguredError
- **禁止** 生图调用依赖内置默认配置 — image_service.py 的 api_key/base_url/model_id 全来自模型管理 image 类型默认配置，无内置默认，未配置报错
- **禁止** 实体 ID 绕过正则白名单（前缀固定 chr_/scn_/clu_/fs_）— WorkspaceStore 以 ID 正则白名单防 glob 注入/路径穿越
- **禁止** 迁移脚本 DROP 表 — backend/scripts/migrate_db_to_workspace.py --cutover 仅 DELETE 行、永不 DROP 表，且前置 shutil.copy2 备份 DB
- **禁止** agent 工具越权写入 — 默认只读白名单 READ_ONLY_TOOLS=[Read,Grep,Glob]，写侧必须经进程内 MCP server 的 upsert_character/scene/clue/foreshadow + save_episode 工具直接调 WorkspaceStore/ScriptManager 落盘
- **必须** 分集设计产出满足强校验自纠：集号连续、伏笔 payoff 晚于 plant、线索 reveal 前置、末集回收（open_ending 豁免）
- **必须** 视频生成前 TimelineBuilder 校验 timeline：每段 ≤9 图 ≤3 音频、段长对齐 5+17n 帧（version=5、fps=24）、overlap 规则
- **必须** 会话加载校验：load_video_session/load_script_session 不存在抛 404；load_script_session 对 workflow_type!='script' 抛 400
- **必须** 步骤执行经 SessionManager.can_execute_step 前置校验；回退时 clear_steps_after 清下游；取消经 _cancelled 标志
- **必须** workspace 写入走原子写（tmp+os.replace）且 per-story RLock；实体 ID 全局分配加锁（SELECT MAX+1，删除回退复用）
- **必须** 生图参考图压缩 RGBA/LA/P 转白底 JPEG（backend/core/utils/image_utils.py 的 compress_image）

## 核心流程

**剧本链**（/script → ScriptWorkflowPage；SCRIPT_STEPS：story_ideation → story_outline → episode_design → lookbook_images）：
1. story_ideation：ideation 多轮盘问（resume 复用 agent session）+ finalize 收敛定稿；ideation/message|finalize 为 POST SSE 直跑（前端组件内边收边渲染），GET/PUT ideation 可回读/编辑
2. story_outline：大纲生成（markmap JSON 导图），outline generate/get/put
3. episode_design：agent 经进程内 MCP server（create_sdk_mcp_server 'script_design' v1.0.0）调写侧工具直接落盘并强校验自纠；episodes generate/regenerate/CRUD、entities CRUD、entities/{id}/references；Episode 字段：episode_id(ep_01)/title/logline/conflict_chain/causality_chain/ending_summary(100-300字)/story_progress(≤600字)/character_ids/scene_ids/clue_refs[{entity_id,action:plant|develop|reveal}]/foreshadow_refs[{entity_id,action:plant|develop|payoff}]
4. lookbook_images：定妆照 agent 出英文 prompt → ImageService 生图+轮询+归档（lb_* pending→completed；list/{imageId}/regenerate|delete）

**视频链**（/ → WorkflowPage；VIDEO_STEPS：select_episode → storyboard_outline → segment_management → generate_videos）：
1. select_episode 从剧本选集：POST /api/v1/sessions/from-script(201)，sessions 表锚定 workspace_path/script_session_id/source_episode_id，兜底 glob
2. storyboard_outline 分镜大纲：agent 检索工作区出 JSON 导图+segments；人工编辑导图解析同步（reconcile）；PUT 更新
3. segment_management 分镜管理/素材/prompt：segments/{i}/config（mode/overlap）、material-pool 与 segments/{i}/reference-images（图池=定妆照 lookbook_lb_* + 分集素材 mat_*）、generate-material（AI 生成素材图）、prompt-context/generate-prompt（video-prompt skill 渐进式披露，skill 同步进 story 工作区 99-references/ 让 agent Read）、segment-management/complete
4. generate_videos 视频生成（videos / cancel-videos / regenerate-videos / restore-videos-backup）：VideoCreationWorkflowV2.generate_videos — ScriptContextService 从 WorkspaceStore 装配剧本上下文 → TimelineBuilder.build 构造 timeline_data（version=5、fps=24、images[]/audios[]、segmentConfig{count,mode:'timeline',segments[{startFrame,endFrame,images,audios,prompt}]}，段长对齐 5+17n 帧，校验每段 ≤9 图 ≤3 音频、overlap 规则）→ COMFYUI_MOCK=true 时本地 OpenCV 合成演示 mp4；真实链路 httpx POST /upload/image 上传素材 → 注入 workflow 模板 → POST /prompt → 轮询 GET /history/{id} → GET /view 下载到 static/videos/

**Agent 调用链（异步 run）**：API 层 start_agent_run(label, factory) → get_run_registry().start 立即返回 run_id → 前端 GET /api/v1/agent-runs/{runId}/events?seq= SSE 观流（断线重连最多 6 次×2s，seq 幂等去重）或 GET /{run_id} 轮询兜底；POST /{run_id}/cancel 经 interrupt_event→client.interrupt()；发起调用前先流出 prompt 事件（提示词透明化，含最终 system/user prompt 与模型名）。无 run 机制的长任务前端用 usePolling 轮询（视频生成 3s、分集生成 2s、定妆照 2s）

**持久化流转**：生成内容 → workspace/{剧名}-{sid8}/ markdown（权威源，原子写）；会话/任务状态 → data/sessions.db（sessions.workspace_path 为锚点，兜底 glob）；旧形状读经 workspace_projection.py 投影回 step_results JSON；历史数据经 backend/scripts/migrate_db_to_workspace.py 迁移

## 演进记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修订 — 填补 VIDEO_STEPS 待补充项（select_episode/storyboard_outline/segment_management/generate_videos）；重连参数归属从 sse.ts 修正到 AgentRunProgress.tsx；workspace_projection.py 位置由 persistence 修正到 services；分镜目录结构修正为 04-storyboards/{ep_xx}/vs-{前8位} 并补 99-references/；COMFYUI_WORKFLOW_PATH 标注模板未入库；image_utils 补全路径 |
