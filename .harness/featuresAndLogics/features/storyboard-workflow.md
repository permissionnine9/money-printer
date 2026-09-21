---
name: 分镜工作流
摘要: 视频创作工作流第 2/3 步（分镜大纲 + 分镜管理）：Agent 在剧本工作区自主检索生成分镜导图与分镜列表，产物文件化存于 04-storyboards/，支持人工编辑导图、分镜形式/overlap 配置、参考素材图管理（素材池选择 + AI 生成 + agent 自动匹配）、单分镜完成态与 video-prompt skill 分镜提示词生成。
tags: 分镜, 视频工作流, AgentSDK, 文件化工作区, SSE
---

# 分镜工作流

**状态:** 已完成
**最后更新:** 2026-09-21

## 功能概述

分镜工作流是视频创作工作流 V2（4 步：select_episode → storyboard_outline → segment_management → generate_videos，见 `backend/core/persistence/session_manager.py` 的 `VIDEO_STEPS`）的第 2/3 步实现，由 `StoryboardWorkflow`（继承 `StepWorkflowBase`）承担：

- **第 2 步 storyboard_outline 分镜大纲**：Agent（READ_ONLY_TOOLS=Read/Grep/Glob，cwd=剧本工作区）以分集设计为上下文自主检索，单次 run 产出 markmap 导图 + 分镜列表；支持人工编辑导图（`### 标题` 行界定分镜，解析后同步 mindmap 与 segments）。
- **第 3 步 segment_management 分镜管理**：分镜形式（4 种，仅全能参考模式实现关联逻辑）与 overlap 配置、参考素材图管理（素材池选择弹窗 + AI 生成素材图 + **agent 自动匹配参考图**）、video-prompt skill 生成分镜提示词、**单分镜完成态**（completeSegment，解锁第 4 步视频生成）。

**权威源文件化**：分镜产物以 markdown 存于剧本工作区 `04-storyboards/{ep_NN}/vs-{视频会话id前8}/`（storyboard.md 导图 + seg_NN-*.md 单镜文件，权威源为 `WorkspaceStore`）；DB step_results 只保留薄 envelope（`{"_artifact": "workspace", "path": "workspace/..."}`）与完成态标志；会话详情经 `video_step_results` 投影把分镜文件内容还原进 `storyboard_outline.result_data`。

数据流：前端 StepStoryboardOutline/StepSegmentManagement → stepApi（axios `/api/v1`）→ backend/api/v1/steps.py（挂载 `/api/v1/steps`）→ StoryboardWorkflow → WorkspaceStore（分镜 markdown 文件）+ SessionManager（步骤完成态，SQLite）；Agent 生成类接口 POST 后立即返回 run_id，前端连 `/api/v1/agent-runs/{run_id}/events` SSE 观流。

## 核心代码路径

- `backend/core/agents/storyboard.py` — 核心业务：`StoryboardWorkflow` 全部逻辑（大纲生成/编辑、分镜配置、参考图管理与自动匹配、素材图生成、提示词生成、单分镜完成态），业务异常 `StoryboardError`（WorkflowError 子类，默认 status_code=400）；构造注入 AgentStepService（`agent_steps`）/ImageTaskService（`image_tasks`）/MaterialPoolService（`materials`）+ script_manager
- `backend/core/services/material_pool_service.py` — 素材池服务（自 agents 层迁入）：`resolve_pool_image`/`list_pool`/`delete_material`/`validate_reference_paths`（防路径穿越）
- `backend/core/services/agent_step_service.py` — Agent 步骤模板收敛：「prompt 准备→run_agent→错误抛异常→解析」统一入口（`AgentStepService.run(label, prompt|template+vars, parse, cwd, mcp_servers, error_cls)`）
- `backend/prompts/segment_material_match.md` — 分镜自动匹配参考素材图模板（分镜提示词生成后调用，输出 `{"image_ids":[...]}`）
- `backend/api/v1/steps.py` — API 层：视频工作流 4 步路由（挂载于 `/api/v1/steps`，见 backend/main.py），第 2/3 步的分镜路由全在此文件
- `backend/core/persistence/workspace_store.py` — 文件化存储权威源：`storyboard_dir`/`write_storyboard`/`read_storyboard`/`replace_storyboard`/`update_segment_fields`/`segment_path`/`episode_path`/`agent_entry`（04-storyboards 目录结构）
- `backend/core/workflows/video_workflow.py` — `VideoCreationWorkflowV2`（自 agents/workflow_v2.py 迁出）：第 1 步选集（分镜上游）与第 4 步视频生成（消费分镜文件）
- `backend/core/agents/workflow_base.py` — `StepWorkflowBase` 基类：`require_step_data`/`ensure_can_execute` 守卫与 `self.prompts`（prompt_manager）
- `backend/core/services/video_prompt_skill.py` — `sync_video_prompt_skill`：把 `backend/.claude/skills/video-prompt/` 同步进工作区 `99-references/video-prompt/`（渐进式披露；skill 已瘦身：SKILL.md 415→136 行，references 合计剩约 250 行，判据式压缩非搬迁）
- `backend/core/services/step_payload.py` — `video_step_results`：会话详情时把分镜文件内容投影回 step_results（无 DB fallback；并注入 comfyui_import 辅助状态）
- `backend/schemas/steps.py` — 请求模型（StoryboardOutlineGenerateRequest/SegmentConfigUpdateRequest/SegmentReferenceImageIn/SegmentMaterialGenerateRequest 等）
- `frontend/src/components/workflow/StepStoryboardOutline.tsx` — 第 2 步前端：预览/编辑双模式导图、重新生成（重生成级联清下游确认）
- `frontend/src/components/workflow/StepSegmentManagement.tsx` — 第 3 步前端：分镜列表、形式/overlap 配置、参考图编辑、提示词生成弹窗（上下文预览 + 观流）
- `frontend/src/components/workflow/material/` — 素材子组件：MaterialPickerModal（素材池选择）、MaterialGenerateModal（AI 生成）、MentionImageInput（@ 引用输入）
- `frontend/src/api/client.ts` — `stepApi`：storyboard-outline/generate|update、segments config/reference-images/generate-material/generate-prompt、material-pool、prompt-context、segment-management/complete
- `backend/core/agents/system_prompts.py` — 系统提示词常量：STORYBOARD_OUTLINE_SYSTEM / MATERIAL_GENERATE_SYSTEM / SEGMENT_PROMPT_SYSTEM
- `backend/core/services/prompt_manager.py` — 用户 prompt 模板：`storyboard_outline`、`material_generate`

## 关键逻辑说明

### API 路由（backend/api/v1/steps.py，挂载前缀 /api/v1/steps）

| 路由 | 处理函数 | 行为 |
|------|---------|------|
| POST /{sid}/storyboard-outline/generate | generate_storyboard_outline | 前置 can_execute_step 校验（不满足 400）；返回 {run_id}（label=storyboard_outline），重生成级联清下游 |
| PUT /{sid}/storyboard-outline | update_storyboard_outline | 保存人工编辑导图（markdown 含 `- 分镜内容` 行） |
| PUT /{sid}/storyboard-segments/{index}/config | update_segment_config | 更新分镜形式/overlap；变化会清空该分镜已生成提示词 |
| GET /{sid}/material-pool | get_material_pool | 素材池分组数据（核心素材图/本集素材/其他集素材，不跨 story） |
| PUT /{sid}/storyboard-segments/{index}/reference-images | update_segment_reference_images | 全量覆盖保存参考图；换图清空该分镜提示词 |
| POST /{sid}/storyboard-segments/{index}/generate-material | generate_segment_material | AI 生成素材图 → {run_id}（label=segment_material_{index}）；API 层先 fail fast 调 validate_segment_material_request（校验失败直接 400 不进 run） |
| GET /{sid}/storyboard-segments/{index}/prompt-context | get_segment_prompt_context | 提示词生成弹窗的上下文预览 |
| POST /{sid}/storyboard-segments/{index}/generate-prompt | generate_segment_prompt | video-prompt skill 生成提示词 → {run_id}（label=segment_prompt_{index}，仅全能参考模式）；成功后可触发 agent 自动匹配参考图（segment_material_match.md） |
| DELETE /{sid}/materials/{material_id} | delete_material | 删除分集素材（MaterialPoolService.delete_material） |
| PUT /{sid}/storyboard-segments/{index}/complete | complete_segment | **单分镜完成态**（completeSegment(sessionId, index, completed)，原「整步完成」演进） |

Agent 观流统一走 `backend/api/v1/agent_runs.py`（GET /{run_id}/events SSE、GET /{run_id}、POST /{run_id}/cancel）；`StoryboardError`（WorkflowError 子类）由 backend/main.py 全局 exception_handler 统一转 HTTP detail。分镜产物投影/装配经 `step_payload.py`（读）与 `workspace_sections.py`（agent prompt 段/薄 envelope/episode_number/get_selected_episode）。

### 文件化存储（backend/core/persistence/workspace_store.py）

- 目录：`workspace/{剧名或未命名剧本}-{剧本会话id前8}/04-storyboards/{ep_NN}/vs-{视频会话id前8}/`（workspace 根默认项目根 `workspace/`，见 backend/core/config.py 的 WORKSPACE_DIR；story 目录名由 `ensure_story` 生成并经 DB 锚点 workspace_path 定位；`storyboard_dir` 确定性拼出，不落库索引）。
- `write_storyboard`：生成大纲时**清空 vs 目录后整体重写**（对应旧级联重置语义，配置与提示词一并重置）；storyboard.md（frontmatter: episode_id/video_session_id/edited/segment_count + 正文 mindmap）+ 每分镜一个 `seg_{index:02d}-{title}.md`（frontmatter: index/title/mode/overlap/duration/edited/reference_images + 正文「分镜大纲」「分镜提示词」两节，行首标题转义）。
- `read_storyboard`：读 storyboard.md + glob seg_*.md，按 index 排序，返回与旧 step_results 同构的 `{mindmap, edited, segments, segment_count}`。
- `replace_storyboard`：人工编辑导图 reconcile 后整体替换（segments 可能增删/改名：先删全部 seg_*.md 再重写；不改 created_at）。
- `update_segment_fields`：单分镜部分更新（mode/overlap/duration/title/outline/prompt/reference_images 白名单过滤，整文件重写并置 edited=True）。
- 读取投影：`video_step_results`（step_payload.py）在会话详情接口把 read_storyboard 结果合入 storyboard_outline.result_data（前端凭此渲染），并注入 comfyui_import 辅助状态（来自 session_manager.save_aux_state）。

### 第 2 步：分镜大纲生成/编辑（storyboard.py）

- `generate_outline`：前置 `ensure_can_execute("storyboard_outline")`；prompt 由模板 `storyboard_outline` 渲染（video_params 上下文 + workspace_section 工作区检索指引 + 用户额外要求 + max_segment_duration）；经 AgentStepService 调 run_agent（system=STORYBOARD_OUTLINE_SYSTEM，tools=READ_ONLY_TOOLS，cwd=story_cwd，max_turns=12）。storyboard_outline.md 模板新增「拍给观众看不是剧情备忘录」约束块（开场即钩子/幕按起承转合/写戏不写事/视觉锚点投资/认知唤起/节奏张弛）；**有人物开口的分镜 outline 必须带台词原文**（下游分镜要生成对白音频）。
- 输出解析：`parse_json_response` 取 JSON，`is_valid_mindmap` 校验 markdown 导图，segments 非空；**LLM 输出的 duration/overlap 不可信**——duration clamp 到 [5, max_segment_duration]、overlap clamp 到 [0,3]、首镜 overlap 固定 0。
- 落库顺序：先 `clear_steps_after`（清 segment_management/generate_videos 下游）→ `write_storyboard`（清目录重写）→ `save_step_result` 薄 envelope。
- `update_outline` 人工编辑：`_SEGMENT_HEADING = re.compile(r"^###\s")` 界定分镜标题（#### 更深层级不构成分镜，与前端 /^###\s/ 一致），其后至下一标题行之间的 `- ` 列表行合并为该分镜 outline 并从 mindmap 中剔除；与旧 segments **按 title 匹配合并**（同名按出现顺序消费；中间增删分镜时按下标配对会整体错位，故不用 index）；title/outline 变化或分镜增删 → 变化分镜清空 prompt，且 segment_management 已完成则回退其完成态（clear_step_result + clear_steps_after + reset_current_step）。写序统一「先写文件（权威源）成功，再回退 DB 完成态」。

### 第 3 步：分镜管理（storyboard.py）

- **分镜形式**：`VALID_SEGMENT_MODES = {first_frame, last_frame, all_reference, first_last_frame}`，仅 **all_reference 全能参考模式**实现 overlap、参考图与提示词生成关联逻辑（StoryboardSegment 字段注释同）。
- `update_segment_config`：mode/overlap **真实变化**（与现值不同）才清空该分镜已生成提示词（提示词内嵌 overlap 语义，幂等写不清空）；非法 mode 抛 400。
- **素材池** `list_material_pool`（MaterialPoolService.list_pool）：分组 = 核心素材图（story 级 lookbook，key=lookbook）+ 本集素材（key=current）+ 其他集素材（key=episode_{eid}，按 ep_NN 集号排序），均不跨 story；素材图 ID 规则 `lookbook_lb_*` 核心素材图 / `mat_*` 分集素材（`resolve_pool_image` 校验存在、同 story、已生成 image_path）；支持 `delete_material` 删除分集素材与 `validate_reference_paths` 防路径穿越。
- **参考图自动匹配（新）**：分镜提示词生成成功后可触发 `_auto_match_reference_images`——agent 按分镜提示词从素材池挑选参考图（模板 `segment_material_match`：输入 segment_context/segment_prompt/candidate_images → 输出 `{"image_ids":[...]}`；只选身份锚定必需图、宁缺毋滥、防构图雷同）；匹配结果写入分镜 reference_images（stale_prompt 语义同手动换图）。
- **参考图保存** `update_segment_reference_images`：仅全能参考模式；全量覆盖（schema 上限 8 张）；description 为空带出库内描述，image_path 总是从素材源刷新（防陈旧路径）；**图片集合变化**（增/删/换图）才清提示词并回退完成态，仅编辑描述不影响。
- **AI 素材图生成** `generate_segment_material`：API 层与 run 内共用 `validate_segment_material_request`（需 all_reference 模式；提示词/@素材/上传参考图至少一项；上传参考路径 resolve 后必须在 static/uploads 内，拒绝 `../..` 路径穿越）。流程：LLM 需求理解（模板 material_generate，MATERIAL_GENERATE_SYSTEM，max_turns=8，产出英文生图 prompt + 中文描述）→ 登记素材池 pending（insert_episode_material，meta.origin=ai）→ 生图（`build_image_service_from_model_config`，OpenAI 协议提交即同步完成，submit + poll 取回；失败/异常回写 task_status=failed）→ `archive_generated_image` 归档 `static/images/{story_name}/{episode_name}/` → 回写 completed → 锁内重读分镜自动关联（stale_prompt=True 清旧提示词）。生图参考图 = @素材 + 上传图，**上限 4 张**（OpenAI edits 协议），超出截断告警。
- **分镜提示词生成** `generate_segment_prompt`：仅全能参考模式；`build_prompt_context` 装配上下文（弹窗预览与 agent 调用共用：全剧大纲/本集脚本/当前与上一分镜/参考图/overlap 规则）；**effective_overlap** = overlap 仅当 index>0 且 mode=all_reference，否则 0；overlap>0 时 prompt 注入上一分镜文件路径与已生成提示词，并要求输出以「接续上一分镜」开头、写明上一镜结尾与本镜起始状态；overlap=0 时禁止出现「接续/承接」字样。skill 规范经 `sync_video_prompt_skill` 同步进工作区 `99-references/video-prompt/`（SKILL.md 136 行 + references 三文件共约 250 行，2026-09-21 已从 ~415+数千行判据式瘦身——压缩为「判据 + 对照表 + 硬约束」非搬迁，Agent SDK 隔离模式无法原生加载项目级 skill 故复制进工作区，prompt 只留必读指引）。run（SEGMENT_PROMPT_SYSTEM，max_turns=16）输出纯文本提示词（拒绝 JSON/解释）写回 prompt 字段。
- **完成标记**：演进为**单分镜完成态** `complete_segment`（PUT /storyboard-segments/{index}/complete，前端 completeSegment(sessionId, index, completed)）——按分镜粒度标记完成/取消完成，第 3 步整体完成度=已完成分镜数（前端 StepNavigator 显示「已完成配置数/总数」）。
- **并发控制**：会话级 `_seg_locks`（threading.Lock，按 session_id 惰性创建）保护配置/参考图/提示词收尾的「读-改-写」分镜文件，防 lost update。

### 前端（frontend/src/components/workflow/）

- `StepStoryboardOutline.tsx`：数据取 `session.step_results.storyboard_outline.result_data`（投影产物）；`buildMindmap` 把 segments 的 outline 拼为 `### 标题` 下的 `- ` 列表子节点（预览模式附加 `Ns · overlap Ns` 后缀，编辑模式不加），编辑保存这份文本由后端解析同步；生成/重生成带额外提示词输入与常用提示词快捷下拉（PRESET_PROMPTS）；有下游完成态时重生成需确认（级联清空提示词与视频数据）。**已迁移全局任务跟踪**：本地 AgentRunProgress 内联观流改为 agentRunStore + RunTaskBanner（useRunActive/useRunError/guardRunStart，kind='storyboard_outline'），跨菜单切换任务不丢；mindmap 变化时渲染期切回预览模式。
- `StepSegmentManagement.tsx`：分镜卡片列表，形式下拉（SEGMENT_OPTIONS），全能参考模式时出现 overlap 滑块、参考素材图编辑区与提示词生成入口；提示词弹窗先 GET prompt-context 展示上下文（剧本大纲/本集脚本/当前分镜/参考图/overlap 衔接信息）再发起生成观流（提交加 confirming 防重复点击守卫，addRun kind='segment_prompt'，提示语「进度见右上角后台任务」）；生成中不允许关闭弹窗；已生成提示词支持复制；按分镜粒度完成标记。
- 页面装配：frontend/src/pages/WorkflowPage.tsx 按 current_step 渲染 StepSelectEpisode/StepStoryboardOutline/StepSegmentManagement/Step6Videos。

### 上下游衔接

- **上游**：第 1 步 select_episode（video_workflow 的选集步骤，校验剧本会话 episode_design 已完成）保存 script_session_id/episode_id/episode_title/video_params；经 `get_selected_episode`（workspace_sections，未完成抛 WorkflowError）读取。视频会话本身由 POST /api/v1/sessions/from-script（backend/api/v1/sessions.py）创建。
- **下游**：第 4 步 `video_workflow` 从 `read_storyboard` 读分镜（content=已生成提示词或分镜大纲，duration=max_segment_duration，reference_images 全能参考图作为该段参考图；http(s) 外链无法上传自动跳过）。

## 依赖与复用关系

- 依赖: AgentSDK（backend/core/agent_sdk：run_agent/AgentRunOptions/READ_ONLY_TOOLS/AgentEvent/AgentRunRegistry，run 提交与 SSE 观流）；WorkspaceStore（分镜 markdown 权威源）；SessionManager（VIDEO_STEPS 步骤完成态，can_execute_step/clear_steps_after/reset_current_step）；StepWorkflowBase（backend/core/agents/workflow_base.py 守卫基类）；ScriptContextService（build_segment_script_context/fetch_lookbook_images，其 scm 即 ScriptManager）；ScriptManager 素材表（insert/update/get/list_episode_materials、get_lookbook，backend/core/persistence/script_manager.py）；build_image_service_from_model_config（backend/core/services/image_service.py，生图模型默认配置消费方）；archive_generated_image（backend/core/utils/image_store.py）；parse_json_response/is_valid_mindmap（backend/core/utils/json_parser.py）；resolve_project_path（backend/core/utils/path_utils.py）；prompt_manager 模板（storyboard_outline/material_generate）；前端 antd、MindmapView（frontend/src/components/common）、AgentRunProgress（frontend/src/components/script/AgentRunProgress.tsx）
- 被依赖: backend/api/v1/steps.py（路由层直接调用）；video_workflow（第 4 步视频生成读分镜文件）；step_payload.video_step_results（会话详情投影）
- 可复用组件: StepWorkflowBase（与 ScriptWorkflow 共用的守卫/事件基类）；video-prompt skill 同步机制（sync_video_prompt_skill，可推广到其他 skill 渐进式披露）

## 注意事项

- **权威源在文件不在 DB**：分镜内容（mindmap/segments/prompt/reference_images）只存 04-storyboards/ 下的 markdown；DB step_results 只有 envelope 与完成态。排查问题先看文件，`video_step_results` 投影是前端看到的唯一出口。
- **写序约定**：所有「变化回退完成态」路径统一先写文件成功、再改 DB（中途失败时文件为准、DB 完成态可安全重试）。
- **提示词失效即清空**：mode/overlap 真实变化、参考图集合变化、导图编辑致 title/outline 变化、AI 素材图自动关联，均会清空对应分镜 prompt 并回退 segment_management 完成态（需重新确认/重新生成提示词）。
- **仅全能参考模式实现完整链路**：first_frame/last_frame/first_last_frame 三种形式可在配置中选择（VALID_SEGMENT_MODES 校验通过），但 overlap/参考图/提示词生成的关联逻辑仅 all_reference 生效。
- **LLM 数值不可信**：大纲阶段 LLM 输出的 duration/overlap 一律 clamp（duration∈[5,max]、overlap∈[0,3]、首镜 0），不落库原始值。
- **安全**：上传参考图路径 resolve 后强制落在 static/uploads 内（防路径穿越）；素材图引用校验同 story 归属。
- **生图参考图上限 4 张**（OpenAI edits 协议），超过截断并 warning；分镜参考图保存上限 8 张（schema max_length=8）。
- **重生成级联清空**：第 2 步重生成会清 04-storyboards/{ep}/vs-{sid}/ 目录整体重写（分镜配置、参考图、提示词全重置）并清下游步骤结果；前端有下游完成态时弹确认。
- **并发**：_seg_locks（分镜收尾）与 WorkspaceStore 的 story 级 RLock 均为进程内 threading 锁，单进程部署下防 lost update；多 worker 部署无跨进程互斥（未实测，待补充）。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析自动生成（feat/create_story 分支文件化改造后的形态） |
| 2026-09-21 | 同步重构 — StoryboardWorkflow 注入 AgentStepService/ImageTaskService/MaterialPoolService（素材池逻辑自 agents 层迁入 material_pool_service.py）；新增参考图自动匹配（segment_material_match.md）、delete_material、单分镜完成态 completeSegment；storyboard_outline.md 增「拍给观众看」约束；video-prompt skill 判据式瘦身（SKILL.md 415→136 行）；投影/装配改 step_payload + workspace_sections；前端迁移全局任务跟踪 |
