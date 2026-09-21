---
name: 项目概述
摘要: AI 剧本/视频创作平台：双 4 步工作流，FastAPI + React 19 前后端分离，claude-agent-sdk 编排 LLM（FIFO 并发队列上限 5），markdown 权威源 + SQLite 会话状态，前端全局任务坞跨页保活。
tags: overview, architecture, constraints
---

# 项目概述

**最后更新:** 2026-09-21

## 概述

money-printer 是一个 AI 剧本/视频创作平台。前端 React 19 + AntD 6 + zustand，后端 FastAPI（uv 管理 Python >= 3.11）。业务上为双 4 步工作流：

- **剧本链**：故事构思 ideation 对话/定稿（或「采纳为故事逻辑」直接完成）→ 大纲 → 分集设计+实体库 → 核心素材图（lookbook）
- **视频链**：从剧本选集 → 分镜大纲 → 分镜管理/素材/prompt → ComfyUI 视频生成

后端入口 `backend/main.py` 创建 FastAPI（title='AI视频创作智能体 API', version='2.0.0', lifespan）：
- lifespan 启动时调 `backend/config.py` 的 `override_src_config()` 打印模型管理默认模型
- CORS 允许 http://localhost:5173 与 :3000；`app.mount('/static', StaticFiles(directory='static'))` 提供图片/视频静态资源
- 全局 exception_handler 只注册单个 `WorkflowError`（backend/core/errors.py，message + status_code 默认 400）handler；ScriptWorkflowError/StoryboardError 继承该基类，由同一 handler 统一转 HTTP
- include_router 8 个模块（sessions/steps/uploads/models/prompts/settings/script_sessions/agent_runs；相较旧版删除 assets、新增 settings），均挂 `/api/v1/*` 前缀；GET `/` 与 `/health` 健康检查；`__main__` 下 uvicorn 0.0.0.0:8000 reload

LLM 编排用 claude-agent-sdk 0.2.154（ClaudeSDKClient 子进程驱动本机 Claude Code CLI）；Agent run 统一经 registry FIFO 排队（并发上限 MAX_CONCURRENT_RUNS=5，queued/started 事件可观测）；生成内容以 `workspace/` frontmatter markdown 为权威源，会话/任务状态存 SQLite `data/sessions.db`。

前端路由（`frontend/src/App.tsx`）：main.tsx 用 BrowserRouter → App.tsx 内 MainLayout 包 Routes：`/script` → ScriptWorkflowPage（剧本 4 步）、`/` → WorkflowPage（视频 4 步）、`/models` → ModelsPage（image/chat/agent 模型配置 CRUD）、`/prompts` → PromptsPage（backend/prompts markdown 模板编辑）。MainLayout 含顶导航（新增 ComfyUIConnectionModal 连接管理入口）+ SessionSider 会话侧栏（grouped 模式：视频会话按引用剧本二级分组）+ AgentRunDock（全局任务坞，跨页面/菜单切换保活 Agent 运行流）。

## 项目目标

- 剧本链 4 步闭环（SCRIPT_STEPS：story_ideation → story_outline → episode_design → lookbook_images）：产出含 conflict_chain/causality_chain/ending_summary(100-300字)/story_progress(≤600字)/clue_refs/foreshadow_refs 的分集、前缀 chr_/scn_/clu_/fs_ 的实体库（description ≤80 字供生图）、以及核心素材图（lookbook，lb_* 任务状态机 pending→completed；中文 prompt：人物三视图 front/side/back、场景全景）；支持跨剧本素材库复用（lookbook library 导入其他剧本已完成的核心素材图）
- 视频链 4 步闭环（VIDEO_STEPS：select_episode → storyboard_outline → segment_management → generate_videos）：从剧本选集 → 分镜大纲 → 分镜管理/素材/prompt → ComfyUI 视频生成；timeline version=5、fps=24、段长对齐 5+17n 帧、每段 ≤9 图 ≤3 音频；产物下载到 `static/videos/`
- 所有 LLM 生成内容以 `workspace/` frontmatter markdown 为权威源；会话/任务状态存 SQLite `data/sessions.db`（WAL）
- Agent 运行支持并发上限 5 的 FIFO 排队（MAX_CONCURRENT_RUNS=5）：queued/started 事件可观测（含 queue_position），排队中可即时取消
- 用户可自助管理 image/chat/agent 三类模型默认配置与 backend/prompts markdown 模板
- 提示词透明化：agent 发起调用前流出 prompt 事件（含最终 system/user prompt 与模型名）；成本可观测（AgentRunResult 含 usage/cost_usd）
- 业务量化目标（KPI）：（待补充）

## 项目架构

- **backend/main.py** — 职责: FastAPI 入口（lifespan 启动打印默认模型、CORS、/static 静态资源、单个 WorkflowError 全局异常 handler、挂载 8 个 `/api/v1/*` router、/ 与 /health 健康检查、uvicorn 启动），依赖: backend/config.py（override_src_config）、backend/core/errors.py（WorkflowError）、backend/api/v1/ 各 router
- **backend/api/v1/** — 职责: 8 个 router。sessions：视频会话 CRUD + POST /from-script(201)；steps：视频步骤面（select-episode、storyboard-outline generate(PUT 更新)、segments/{i}/config、material-pool、materials/{image_id} 删除、segments/{i}/reference-images、generate-material、prompt-context、generate-prompt、segments/{i}/complete（原 segment-management/complete 演进为单分镜 complete_segment）、videos（支持 segmentIndexes 指定段生成）/comfyui/import/comfyui/start/cancel-videos/restore-videos-backup）；script_sessions：会话 CRUD + ideation/message|finalize（POST SSE 直跑）+ GET/PUT ideation + ideation/title（set_story_title）+ ideation/adopt（adopt_story_logic 采纳故事逻辑直接完成第 1 步）+ outline generate/get/put + episodes generate/regenerate/CRUD + entities CRUD + entities/{id}/references + lookbook generate/complete/list/{imageId}/regenerate|delete + lookbook/library（GET 跨剧本素材库查询）+ lookbook/import（POST 素材库导入）；agent_runs：GET /{run_id}/events?seq=（SSE 观流）、GET /{run_id}（轮询兜底）、POST /{run_id}/cancel；models/prompts/uploads(/image) CRUD；**settings.py（新增，121 行）**：GET/PUT /comfyui-connection — 读写 ~/.claude/skills/comfyui-restart/hosts.json 的 gz15-a100 条目（密码脱敏）、杀旧 SSH 隧道重启 start_comfyui_tunnel.sh、35s 轮询探测 127.0.0.1:8188 连通。已删除：assets router（素材管理台 CRUD 已删）与 _upload.py（落盘逻辑内联进 uploads.py，含 save_upload/UPLOAD_ROOT/MAX_UPLOAD_SIZE），依赖: backend/deps.py 提供的单例
- **backend/deps.py** — 职责: lru_cache 单例依赖注入。get_session_manager()=SessionManager(steps=VIDEO_STEPS)、get_storyboard_workflow()=StoryboardWorkflow（注入 script_manager）、get_script_session_manager()=SessionManager(steps=SCRIPT_STEPS)（双 4 步参数化）、get_script_manager()=ScriptManager、get_model_manager()=ModelManager（共用同一 SQLite）、get_workspace_store()=WorkspaceStore（markdown 权威源）、get_workflow()（自 backend.core.workflows.video_workflow 导入，改 @lru_cache 单例并注入 store）、get_script_workflow()（新增）；load_video_session/load_script_session 校验；run_agent_endpoint(label, factory)（原 start_agent_run 改名，签名不变）统一 `{'success':True,'data':{'run_id':...}}` 响应，依赖: SessionManager/ScriptManager/ModelManager/WorkspaceStore/StoryboardWorkflow/VideoCreationWorkflowV2/ScriptWorkflow、get_run_registry()
- **backend/core/agent_sdk/** — 职责: claude-agent-sdk 封装。wrapper.run_agent/run_conversation（AgentRunOptions：prompt/system_prompt/max_turns=40/tools 默认只读白名单 READ_ONLY_TOOLS=[Read,Grep,Glob]/mcp_servers/cwd 锁定剧本工作区/resume 多轮/interrupt/env；permission_mode=bypassPermissions、setting_sources=[]、include_partial_messages=True、max_thinking_tokens=6000、max_buffer_size=MAX_STREAM_BUFFER_SIZE=16MB（SDK stream-json 单条消息上限，防 Agent Read 图片 base64 撑爆默认 1MB）；**已删除 output_format JSON Schema 结构化输出** — AgentRunOptions.output_format、AgentRunResult.structured_output、run_conversation 的 tools/mcp_servers 参数均删）；**direct.py（新增）**：sse_direct_response — SSE 请求内直跑编排便，asyncio.Queue 中转事件，final/[DONE] 帧收尾，客户端断开 5s 宽限后取消；model_env.build_agent_env() 注入 ANTHROPIC_* 环境变量（CLAUDE_AGENT_SDK_CLIENT_APP=money-printer/2.0）；registry.AgentRunRegistry 进程内单例（run_id 12 位 hex、events deque maxlen=5000 带 seq、MAX_RUNS=200、asyncio.Condition 驱动；**FIFO 排队 + MAX_CONCURRENT_RUNS=5**：5 个常驻 worker 协程消费 deque 待跑队列，run status queued→running→done，入队 emit queued（含 queue_position）、领取 emit started，排队中 cancel 立即落终态、worker 领取时跳过已 done）；events.py 事件归一（type ∈ thinking/text_delta/tool_use/tool_result/result/error/prompt/queued/started，新增 queue_position 字段，to_sse 输出 data 行），依赖: claude-agent-sdk 0.2.154、ModelManager.get_default_model('agent')
- **backend/core/agents/** — 职责: `script_workflow.py`（ScriptWorkflow：注入 agent_steps/image_tasks service；剧本链 ideation 多轮盘问 resume 复用 agent session + finalize 收敛、adopt_story_logic 采纳故事逻辑直接完成第 1 步不经 LLM 收敛、set_story_title 剧名 ≤60 字；大纲 markmap JSON 导图；分集设计经进程内 MCP server（create_sdk_mcp_server 'script_design' v1.0.0）注册 upsert_character/scene/clue/foreshadow + save_episode 五写工具直接调 WorkspaceStore/ScriptManager 落盘；核心素材图 agent 出中文 prompt：人物三视图 front/side/back、场景全景）；`storyboard.py`（StoryboardWorkflow：注入 agent_steps/image_tasks/materials service；分镜大纲 agent 检索工作区出 JSON 导图+segments、人工编辑导图解析同步 reconcile、分镜 mode/overlap 配置、参考素材图池、AI 生成素材图、分镜提示词生成后 _auto_match_reference_images 配 segment_material_match.md 自动挑选参考素材图（输出 {"image_ids":[...]}）、delete_material、complete_segment 单分镜完成态），依赖: backend/core/agent_sdk/、backend/core/services/、backend/core/persistence/workspace_store.py
- **backend/core/workflows/**（新包）— 职责: `video_workflow.py`（617 行，自 agents/workflow_v2.py 迁出，类名仍 VideoCreationWorkflowV2）：generate_videos 视频生成链，新增 run_generate_videos_sync、mark_videos_generating/restore_videos_backup（备份恢复）、prepare_comfyui_import/_execute_imported_videos（「导入到 ComfyUI」：上传素材 + 注入 timeline_data + 把注入后的 UI 版工作流写到服务器 user/default/workflows/money-printer/导入_{会话ID}.json）、_auto_global_prompt（全局提示词注入，带容错）、_resolve_generation_segments（按 segmentIndexes 指定段生成），依赖: backend/core/services/（comfyui_service/script_context_service 等）
- **backend/core/services/** — 职责: agents 层逻辑下沉的 services 编排层。新增：`agent_step_service.py`（AgentStepService.run 收敛 agents 层 6 处「prompt 准备→run_agent→错误抛异常→解析」模板）；`image_task_service.py`（ImageTaskService+ImageTaskSpec：生图任务状态机 pending→processing→completed/failed，run_batch 间隔限流批量提交+gather 并发轮询、run_single，update_row 回调适配 lookbook/mat_* 两类表，on_completed 归档钩子）；`material_pool_service.py`（MaterialPoolService：resolve_pool_image/list_pool/delete_material/validate_reference_paths 防路径穿越）；`step_payload.py`（script_step_results/video_step_results/script_title 投影，**无 DB 旧数据 fallback，文件为唯一权威源**，视频侧注入 comfyui_import 辅助状态；替代已删除的 workspace_projection.py）；`workspace_sections.py`（workspace_section/workspace_envelope/episode_number/load_story_logic/load_story_outline/get_selected_episode，agent 装配层）；`lookbook_library_service.py`（list_lookbook_library 跨剧本已完成核心素材图分组查询（当前组排第一+死会话过滤）、import_lookbook_from_library 复制源行为新行（meta 记 imported_from 溯源+回写实体锚点+失败回滚））；`regeneration.py` 改为 cascade_regenerate(sm,store,scm,sid,step) services 层编排（clear_steps_after→delete_story_content→delete_script_data(keep_completed_lookbooks=True) 保留已完成素材进素材库）；既有 `comfyui_service.py`（含 TimelineBuilder：上传素材→注入 workflow 模板→POST /prompt→轮询 /history→下载；COMFYUI_MOCK=true 时本地 OpenCV 合成演示 mp4）、`image_service.py`（OpenAI 兼容协议生图+重试+归档）、`video_prompt_skill.py`（skill 同步进 99-references/，同步逻辑未变）、`prompt_manager.py`、`script_context_service.py` 职责不变；OSSService（oss_service.py，boto3 S3 兼容、3 次重试）与 http_utils.download_to_file 均无调用方（预留/遗留未定），依赖: backend/core/config.py 常量、模型管理 image 类型默认配置
- **backend/core/persistence/** — 职责: `workspace_store.py`（workspace/ frontmatter markdown 权威源：原子写 tmp+os.replace、per-story RLock、实体 ID 全局分配锁、ID 正则白名单（ep_[0-9]{2,}、(chr|scn|clu|fs)_[0-9]{3,}）防 glob 注入/路径穿越、## 标题转义往返、MAP.md 自动渲染；新增 read_story_title/set_story_title、entity_references/delete_entity_unreferenced（引用检查与安全删除）、delete_last_episode）；`base.py`（BaseSQLiteManager，WAL，数据库路径 data/sessions.db 硬编码于此；_connect() 改 @contextmanager 显式 conn.close()（修复 sqlite fd 泄漏），_init_database 同步改造）；`session_manager.py`（SCRIPT_STEPS/VIDEO_STEPS 4 步定义与步骤状态机不变；新增 save_aux_state（辅助状态如 comfyui_import，复用 step_results 表不推进状态机）与 rollback_completion（回退完成态）；删除 delete_step_result/get_latest_session/is_step_cancelled）；`script_manager.py`（lookbook_images/episode_material_images DAO；退役 episodes/script_entities 影子表（删 DDL 与读写，仅迁移脚本维护）；新增 list_completed_lookbooks（全局 completed 且 image_path 非空）、insert_lookbook 新增 image_path/meta 参数（可直接落 completed 行）、delete_script_data 增加 keep_completed_lookbooks 参数），依赖: SQLite 表 sessions/step_results/session_assets/lookbook_images/episode_material_images/image_models
- **backend/core/models/video_models.py** — 职责: StoryboardSegment（index 0 起、title、outline 80-150 字、mode ∈ first_frame/last_frame/all_reference/first_last_frame 默认 all_reference、overlap 0-3 默认 1 且首镜固定 0、duration 5-30s 默认 15、prompt、reference_images）与 VideoParams（resolution='1080p'、aspect_ratio='16:9'、max_segment_duration=15(5-30)、overlap_seconds=0.0(0-5)、to_prompt_context()）pydantic 模型；仅 all_reference 模式实现 overlap/提示词生成逻辑（video_models 字段描述与 storyboard.py 注释一致，其余三模式关联逻辑未实现）
- **backend/core/config.py** — 职责: 配置常量（backend/.env load_dotenv override=True 覆盖）：COMFYUI_BASE_URL 默认 http://127.0.0.1:8188、COMFYUI_MOCK 默认 true、COMFYUI_WORKFLOW_PATH 改指向 comfyUI-flow/ComfyUI-MiniMaxH3-TimelineDirector/example_workflows/..._api.json、COMFYUI_WORKFLOW_UI_PATH（新增，UI 格式模板，「导入到 ComfyUI」写服务器用）、RESOLUTION_OPTIONS=["480p","720p","1080p","4K"]（新增 480p）、COMFYUI_TIMELINE_FPS=24、OSS_ACCESS_KEY/SECRET_KEY/BUCKET 默认空、OSS_ENDPOINT 默认 http://oss-cn-guangzhou.aliyuncs.com、OSS_REGION 默认 cn-guangzhou
- **frontend/src/** — 职责: React 19 + AntD 6 + zustand 前端。两层 API：axios baseURL /api/v1 做 CRUD/触发 + `frontend/src/api/sse.ts` 原生 fetch+ReadableStream 手写 SSE 解析（POST 直跑与 GET 观流共用）；断线重连逻辑在 `AgentRunProgress.tsx`（MAX_RETRIES=6 × RETRY_INTERVAL=2000ms，按 lastSeq 增量续传+赋值幂等去重）；**全局任务坞体系（新增）**：agentRunStore（zustand 全局 store，runs: AgentRunTask[] 队列，kind 四类 segment_prompt/outline/episodes/storyboard_outline，status queued/running/success/error）+ AgentRunDock（挂 MainLayout，每 run 一个 forceRender 保活 Modal 内嵌 AgentRunProgress，收起不卸载 SSE 不断流，成功按 kind 提示并刷新对应 store，失败标红留列）+ RunTaskBanner（进行中/失败横幅）+ useRunTask（guardRunStart 防重复入队/useRunActive/useRunError）；StepOutline/StepEpisodeDesign/StepStoryboardOutline/StepSegmentManagement 均迁移到全局任务跟踪；MainLayout 废弃 navigateWithSession 改 SPA 内切换、顶栏新增 ComfyUIConnectionModal 入口；SessionSider 支持 grouped 模式（视频会话按引用剧本二级分组）；usePolling 新增 maxPolls/onMaxPolls；client.ts 新增 settingsApi/scriptStepApi.setStoryTitle/adoptStoryLogic/getLookbookLibrary/importLookbookImage/stepApi.importComfyUI 等，删除 assetApi 与 regenerateVideos；既有组件 PromptViewerModal（查看最终提示词）、MindmapView（markmap-lib/view）、LazyVideo（IntersectionObserver 懒加载）、scriptMarkdown.ts（拼装完整剧本 Blob 下载）、MentionImageInput（@图片引用输入）职责不变；Step6Videos.tsx 为第 4 步「视频」的遗留文件名（仍 4 步）；无 localStorage/持久层，会话恢复靠 URL ?session_id=；已知 markdown-it 被 StepEpisodeDesign.tsx 直接 import 但未声明在 package.json dependencies（靠 markmap-lib 传递依赖，依赖漂移风险），依赖: vite dev 代理 /api 与 /static → http://localhost:8000（dev 端口 5173 host 0.0.0.0）
- **comfyUI-flow/**（未跟踪目录）— 职责: 第三方开源插件仓 ComfyUI-MiniMaxH3-TimelineDirector（MiniMax H3 无限时长分段长视频生成：分段续接 AV Latent、同种子、音画合并），本项目视频生成后端方案；config.py 的 COMFYUI_WORKFLOW_PATH（API 格式）与 COMFYUI_WORKFLOW_UI_PATH（UI 格式模板）均取自其 example_workflows
- **启动脚本** — 职责: start_comfyui_tunnel.sh（新增，97 行）：SSH 隧道 gz15-a100:8188 → 本地 127.0.0.1:8188，凭据复用 comfyui-restart skill 的 hosts.json，幂等断线重连；start_all.sh 集成随主服务拉起隧道
- **backend/prompts/ 与 backend/.claude/skills/video-prompt/** — 职责: 全面强化「导演二度创作+观众视角」。script_outline.md 大改（角色改「资深导演兼叙事设计师」、观众三问、四组导演决策、恰好 4 个全局分支、防「第N集」子节点误判）；episode_design.md（短剧观感：开场钩子/冷开场/台词要点，story_progress 三线改四线）；storyboard_outline.md（拍给观众看不是剧情备忘录）；新增 segment_material_match.md（分镜提示词生成后自动挑选参考素材图，输出 {"image_ids":[...]}）；lookbook_prompts.md（定妆照→核心素材图：人物三视图 front/side/back、场景全景，prompt 从英文改中文 130-220 字）；video-prompt skill 纯瘦身（SKILL.md 415→136 行，references 合计剩 387 行，判据式压缩非搬迁，同步逻辑 video_prompt_skill.py 未变）
- **backend/scripts/migrate_db_to_workspace.py** — 职责: SQLite → workspace 迁移 CLI（argparse --export/--verify/--cutover/--purge-tables；--export 幂等导出；--verify 双向对账忽略时间戳/edited，差异非零退出；--cutover 前置检查 → shutil.copy2 备份 DB（sessions.db.bak-YYYYmmdd-HHMMSS）→ 内容行替换薄 envelope → 可选 DELETE episodes/script_entities、永不 DROP 表；cutover 后自动停用 export/verify）
- **tests/manual/** — 职责: 6 个非 pytest 手动脚本（__main__ 直接跑）：test_agent_sdk.py（SDK 流式/resume/interrupt/MCP 验证）、test_phase1_data.py（文件化架构下测试：实体/分集读写走 WorkspaceStore）、test_workspace_store.py（文件化 CRUD、路径穿越封堵白名单正则、标题转义双射、8 线程并发原子写、跨会话 ID 隔离、级联清理 delete_story_content/delete_story）、test_narrative_prompt_chain.py（叙事链路注入回归：_auto_global_prompt 容错/新大纲格式集数正则计数防「第N集」子节点误判）、test_agent_run_queue.py（队列：峰值恰 5/FIFO/排队取消即时终态/queue_position 排除已取消/queued→started 顺序）、test_lookbook_library.py（素材库：保留语义/跨会话过滤/insert_lookbook 新参/级联保留/HTTP 层）
- **workspace/、data/、static/** — 职责: 存储层。`workspace/{剧名}-{sid8}/` story 树 = MAP.md + 00-ideation/ + 01-outline/ + 02-episodes/ + 03-entities/ + 04-storyboards/{ep_xx}/vs-{视频会话id前8位}/（同分集多次视频会话=兄弟 vs 目录）+ 99-references/（video-prompt skill 同步目录）；`data/sessions.db` 会话/任务状态（sessions 表：session_id PK、workflow_type 'video'|'script'、current_step、status active/completed/error、workspace_path、script_session_id、source_episode_id；step_results 为薄 envelope {_artifact:'workspace',path}，save_aux_state 亦复用此表存辅助状态）；`static/images/`、`static/videos/` 生成产物

## 设计原则

| 决策 | 理由 | 日期 |
|------|------|------|
| 生成内容文件化：workspace/ frontmatter markdown 为权威源，SQLite step_results 仅薄 envelope {_artifact:'workspace',path} | 生成内容可读可编辑、迁移脚本可双向对账（--verify）；会话/任务状态仍由 SQLite（WAL）承担；step_payload.py 投影无 DB 旧数据 fallback，文件为唯一权威源 | 2026-09-19 |
| LLM 编排用 claude-agent-sdk 0.2.154 子进程驱动本机 Claude Code CLI | ClaudeSDKClient 支持 resume 多轮、interrupt 取消、max_buffer_size 扩容（16MB 防 Read 图片 base64 超限）；默认只读白名单 READ_ONLY_TOOLS=[Read,Grep,Glob]，写侧统一收敛到进程内 MCP server 写侧工具直接落盘 | 2026-09-19 |
| 长任务统一 run_id 异步模型 | POST 即返 run_id（AgentRunRegistry 进程内单例：events deque maxlen=5000 带 seq、MAX_RUNS=200），SSE 按 seq 回放+实时（asyncio.Condition 驱动），GET 轮询兜底，取消经 interrupt_event→client.interrupt() | 2026-09-19 |
| workspace 原子写 + 多级锁 + ID 白名单 | tmp+os.replace 原子写、per-story RLock、实体 ID 全局分配锁、ID 正则白名单防 glob 注入/路径穿越；8 线程并发原子写有 tests/manual/test_workspace_store.py 覆盖 | 2026-09-19 |
| COMFYUI_MOCK 默认 true | 无 ComfyUI 环境时本地 OpenCV 合成演示 mp4，保证视频链路端到端可演示 | 2026-09-19 |
| 双 4 步参数化 SessionManager | get_session_manager()/get_script_session_manager() 以 steps=VIDEO_STEPS/SCRIPT_STEPS 参数化复用同一状态机（推进/回退/can_execute_step 前置校验/clear_steps_after 清下游/_cancelled 取消标志） | 2026-09-19 |
| 前端 4 步子组件 display:none keep-alive 不卸载 | 切换步骤时保 SSE/轮询不断 | 2026-09-19 |
| run 并发队列（MAX_CONCURRENT_RUNS=5 + FIFO + queued/started 事件） | 防止并发 agent 任务压垮模型端点与子进程数；排队可观测可即时取消 | 2026-09-21 |
| WorkflowError 统一异常基类（core/errors.py） | 消除三类业务异常各自 __init__ 样板，main.py 单 handler 覆盖 | 2026-09-21 |
| agents 层逻辑下沉 services（agent_step/image_task/material_pool/step_payload/workspace_sections） | agent 编排与状态机/投影/装配解耦，6 处模板收敛 | 2026-09-21 |
| 前端全局任务坞（agentRunStore+Dock+保活 Modal） | 任务跨页面/菜单切换不丢流，SSE 不断 | 2026-09-21 |
| （待补充） | 更多原则请通过 /harness-update 补充 | - |

## 不可违背的核心逻辑

- **禁止** 未配置模型管理 agent 类型默认模型即发起 agent 调用 — model_env.build_agent_env() 从 ModelManager.get_default_model('agent') 读 base_url/api_key/model_id 注入 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN+ANTHROPIC_API_KEY（双注入）/ANTHROPIC_MODEL，未配置抛 AgentModelNotConfiguredError
- **禁止** 生图调用依赖内置默认配置 — image_service.py 的 api_key/base_url/model_id 全来自模型管理 image 类型默认配置，无内置默认，未配置报错
- **禁止** 实体 ID 绕过正则白名单（前缀固定 chr_/scn_/clu_/fs_）— WorkspaceStore 以 ID 正则白名单防 glob 注入/路径穿越
- **禁止** 迁移脚本 DROP 表 — backend/scripts/migrate_db_to_workspace.py --cutover 仅 DELETE 行、永不 DROP 表，且前置 shutil.copy2 备份 DB
- **禁止** agent 工具越权写入 — 默认只读白名单 READ_ONLY_TOOLS=[Read,Grep,Glob]，写侧必须经进程内 MCP server 的 upsert_character/scene/clue/foreshadow + save_episode 五工具直接调 WorkspaceStore/ScriptManager 落盘（script_design MCP 五写工具不变）
- **禁止** 绕过 ImageTaskService 手写生图任务状态机 — 三处统一（核心素材图批量/单张重生成/分集素材图）均走 ImageTaskService+ImageTaskSpec（pending→processing→completed/failed）
- **必须** Agent run 经 registry 排队（MAX_CONCURRENT_RUNS=5 FIFO）— 不得自行 create_task 跑 agent
- **必须** 分集设计产出满足强校验自纠：集号连续、伏笔 payoff 晚于 plant、线索 reveal 前置、末集回收（open_ending 豁免）
- **必须** 视频生成前 TimelineBuilder 校验 timeline：每段 ≤9 图 ≤3 音频、段长对齐 5+17n 帧（version=5、fps=24）、overlap 规则
- **必须** 会话加载校验：load_video_session/load_script_session 不存在抛 404；load_script_session 对 workflow_type!='script' 抛 400
- **必须** 步骤执行经 SessionManager.can_execute_step 前置校验；回退时 clear_steps_after 清下游；取消经 _cancelled 标志
- **必须** workspace 写入走原子写（tmp+os.replace）且 per-story RLock；实体 ID 全局分配加锁（SELECT MAX+1，删除回退复用）
- **必须** 生图参考图压缩 RGBA/LA/P 转白底 JPEG（backend/core/utils/image_utils.py 的 compress_image）
- **必须** 所有 SQLite 访问走 `with self._connect() as conn:`（@contextmanager 显式 close，防 fd 泄漏），禁止返回裸连接

## 核心流程

**剧本链**（/script → ScriptWorkflowPage；SCRIPT_STEPS：story_ideation → story_outline → episode_design → lookbook_images）：
1. story_ideation：ideation 多轮盘问（resume 复用 agent session），支持两种完成路径 — 「让 AI 收敛故事逻辑」（finalize LLM 收敛定稿）或「采纳为故事逻辑」（ideation/adopt → adopt_story_logic 直接完成第 1 步不经 LLM 收敛；AI 输出匹配「核心情境：」自动填入编辑框）；ideation/message|finalize 为 POST SSE 直跑（前端组件内边收边渲染），GET/PUT ideation 可回读/编辑，ideation/title → set_story_title（剧名 ≤60 字）
2. story_outline：大纲生成（markmap JSON 导图），outline generate/get/put
3. episode_design：agent 经进程内 MCP server（create_sdk_mcp_server 'script_design' v1.0.0）调写侧工具直接落盘并强校验自纠；episodes generate/regenerate/CRUD、entities CRUD、entities/{id}/references；Episode 字段：episode_id(ep_01)/title/logline/conflict_chain/causality_chain/ending_summary(100-300字)/story_progress(≤600字)/character_ids/scene_ids/clue_refs[{entity_id,action:plant|develop|reveal}]/foreshadow_refs[{entity_id,action:plant|develop|payoff}]
4. lookbook_images：核心素材图 agent 出中文 prompt（人物三视图 front/side/back、场景全景）→ ImageTaskService 生图+轮询+归档（lb_* pending→completed；list/{imageId}/regenerate|delete）；素材库导入（GET lookbook/library 跨剧本已完成素材分组查询 + POST lookbook/import 复制源行为新行，meta 记 imported_from 溯源）；级联重生成保留已完成素材（delete_script_data(keep_completed_lookbooks=True)）

**视频链**（/ → WorkflowPage；VIDEO_STEPS：select_episode → storyboard_outline → segment_management → generate_videos）：
1. select_episode 从剧本选集：POST /api/v1/sessions/from-script(201)，sessions 表锚定 workspace_path/script_session_id/source_episode_id，兜底 glob
2. storyboard_outline 分镜大纲：agent 检索工作区出 JSON 导图+segments；人工编辑导图解析同步（reconcile）；PUT 更新
3. segment_management 分镜管理/素材/prompt：segments/{i}/config（mode/overlap）、material-pool 与 segments/{i}/reference-images（图池=核心素材图 lookbook_lb_* + 分集素材 mat_*，MaterialPoolService.validate_reference_paths 防路径穿越）、generate-material（AI 生成素材图）、prompt-context/generate-prompt（video-prompt skill 渐进式披露，skill 同步进 story 工作区 99-references/ 让 agent Read；生成后 _auto_match_reference_images 配 segment_material_match.md 自动挑选参考素材图）、segments/{i}/complete（单分镜 complete_segment 完成态）
4. generate_videos 视频生成（videos（可 segmentIndexes 指定段，_resolve_generation_segments）/cancel-videos/restore-videos-backup（备份恢复）/comfyui/import）：VideoCreationWorkflowV2（backend/core/workflows/video_workflow.py）— ScriptContextService 从 WorkspaceStore 装配剧本上下文 → TimelineBuilder.build 构造 timeline_data（version=5、fps=24、images[]/audios[]、segmentConfig{count,mode:'timeline',segments[{startFrame,endFrame,images,audios,prompt}]}，段长对齐 5+17n 帧，校验每段 ≤9 图 ≤3 音频、overlap 规则）→ COMFYUI_MOCK=true 时本地 OpenCV 合成演示 mp4；真实链路 httpx POST /upload/image 上传素材 → 注入 workflow 模板 → POST /prompt → 轮询 GET /history/{id} → GET /view 下载到 static/videos/；「导入到 ComfyUI」：上传素材 + 注入 timeline_data + 把 UI 版工作流写到服务器 user/default/workflows/money-printer/导入_{会话ID}.json

**Agent 调用链（异步 run）**：API 层 run_agent_endpoint(label, factory) → get_run_registry().start 入 FIFO 队列立即返回 run_id（超出 MAX_CONCURRENT_RUNS=5 排队：queued 事件含 queue_position → started → 执行）；前端全局任务坞消费（agentRunStore 入队 → AgentRunDock 保活 Modal 内 AgentRunProgress）GET /api/v1/agent-runs/{runId}/events?seq= SSE 观流（断线重连最多 6 次×2s，seq 幂等去重）或 GET /{run_id} 轮询兜底；POST /{run_id}/cancel 经 interrupt_event→client.interrupt()（排队中 cancel 立即落终态）；发起调用前先流出 prompt 事件（提示词透明化，含最终 system/user prompt 与模型名）。无 run 机制的长任务前端用 usePolling 轮询（视频生成 3s、分集生成 2s、核心素材图 2s；新增 maxPolls/onMaxPolls 上限保护）

**持久化流转**：生成内容 → workspace/{剧名}-{sid8}/ markdown（权威源，原子写）；会话/任务状态 → data/sessions.db（sessions.workspace_path 为锚点，兜底 glob）；step_payload.py 投影 script_step_results/video_step_results/script_title（无 DB 旧数据 fallback，文件为唯一权威源；视频侧注入 comfyui_import 辅助状态，经 save_aux_state 复用 step_results 表不推进状态机）；历史数据经 backend/scripts/migrate_db_to_workspace.py 迁移

## 演进记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修订 — 填补 VIDEO_STEPS 待补充项（select_episode/storyboard_outline/segment_management/generate_videos）；重连参数归属从 sse.ts 修正到 AgentRunProgress.tsx；workspace_projection.py 位置由 persistence 修正到 services；分镜目录结构修正为 04-storyboards/{ep_xx}/vs-{前8位} 并补 99-references/；COMFYUI_WORKFLOW_PATH 标注模板未入库；image_utils 补全路径 |
| 2026-09-21 | 全量同步 — 架构重构（workflows/services/errors）、Agent 运行队列、核心素材图与素材库、前端全局任务坞、ComfyUI 隧道体系 |
