---
name: 剧本上下文装配逻辑
摘要: 剧本侧上下文装配：workspace_sections 共享装配段（工作区段/选集/故事逻辑）+ ScriptContextService 装配分镜上下文（分集设计/实体卡/伏笔关联/大纲摘要）+ step_payload 投影读侧
tags: 剧本上下文, workspace_sections, ScriptContextService, 分镜提示词, 实体卡, 核心素材图, 素材池, step_payload
---

# 剧本上下文装配逻辑

**最后更新:** 2026-09-21

## 逻辑概述

剧本侧（4 步剧本会话）到视频侧（V2 4 步视频工作流）的上下文装配分布在三层：

1. **共享装配段（services 层收敛）** — `backend/core/services/workspace_sections.py`（83 行），把原本散在 agents 层各处重复实现的装配逻辑收敛为模块级函数：
   - `workspace_section(store, script_session_id, episode_id=None)` — agent prompt 的「剧本工作区」段（目录路径 + MAP 摘要；episode_id 非空时裁剪到本集视角：本集分集设计必读 + 跨集检索指引，为空时给全剧目录地图）；
   - `workspace_envelope(store, script_session_id, rel)` — 步骤结果薄 envelope（内容产物落 workspace 文件，DB 行只留 `{"_artifact": "workspace", "path": ...}` 定位指针）；
   - `episode_number(episode_id)` — `ep_01 → 1`（解析失败返回极大值 10^9，排序时排在最后）；
   - `load_story_logic(store, sm, session_id)` — 故事逻辑读取（工作区文件权威源，**保留 DB 旧数据 fallback**：文件为空时读 `story_ideation` 步骤 result_data.story_logic）；
   - `load_story_outline(store, script_session_id)` — 全剧大纲 mindmap 读取；
   - `get_selected_episode(sm, session_id)` — 视频会话选集信息（script_session_id / episode_id / video_params）；步骤不存在抛 `WorkflowError`（backend/core/errors.py 基类），文案含旧会话不兼容提示（「旧会话不兼容，请从『创作剧本』重新开始」）。
   - 消费方：storyboard.py / script_workflow.py / video_workflow.py / script_context_service.py / material_pool_service.py（原 agents 层本地 `_workspace_section` / `_load_story_logic` / `_episode_number` 等方法已删除）。
2. **分镜上下文装配** — `ScriptContextService`（`backend/core/services/script_context_service.py`，138 行）：给定 `(script_session_id, episode_id)` 产出供分镜脚本生成与前端预览消费的剧本上下文文本。
3. **投影读侧** — `backend/core/services/step_payload.py`（替代已删除的 workspace_projection.py）：`script_step_results` / `video_step_results` / `script_title` 把 DB 薄 envelope 行 + workspace 文件装回旧 step_results 响应形状（markdown 类步骤 result_data 为文件内容形状，**无 DB 旧数据 fallback**；视频侧额外注入 `comfyui_import` 辅助状态，前端据此显示「已导入」）。

数据源分工：markdown 产物（分集设计/实体卡/全剧大纲）以工作区文件为权威源，经 `WorkspaceStore` 读取；核心素材图（原「定妆照」lookbook）/素材图的任务状态仍读 DB（`ScriptManager`，构造属性名 `scm`）。素材池装配已从本服务迁出至 `MaterialPoolService`（见下）。

`build_segment_script_context` 的装配优先级（各段超长截断，保证 prompt 总量可控）：

1. 本集分集设计全文（标题/梗概/矛盾链/因果链/结尾摘要 + 节点进展 story_progress，全文注入不截断）
2. 上一集结尾摘要（按 `ep_NN` 序号定位 N-1 的相邻集；ep_01 无；截断上限 `RELATED_EPISODE_MAX_CHARS * 2` = 600 字）
3. 本集引用的人物/场景实体卡（`character_ids + scene_ids`；单卡上限 280 字；人物卡附加内在动机摘要，上限 150 字）
4. 伏笔/线索关联集摘要（本集 `foreshadow_refs ∪ clue_refs` 与其它集 refs 求交集反查；单条上限 300 字）
5. 全剧大纲摘要（outline.md 的 mindmap；`\n#` 压平为空格后截断 3500 字，作压缩兜底）

常量（模块级）：`OUTLINE_MAX_CHARS=3500`、`ENTITY_CARD_MAX_CHARS=280`、`RELATED_EPISODE_MAX_CHARS=300`、`MOTIVATION_MAX_CHARS=150`、`MOTIVATION_KEYS=("性格","欲望","身份","伤口")`。`_truncate` 超限时截断并追加 `…（截断）`。

当前消费格局（重要）：分镜提示词生成的 agent prompt 为**渐进式披露**——`generate_segment_prompt` 的 user_prompt 不再全文注入 `episode_context`，只注入剧本工作区段（`workspace_section`，含目录地图 + 必读本集分集设计 + 检索指引）+ 视频参数 + 当前/上一分镜 + 参考素材图 + 衔接规则，由 agent 在剧本目录内用 Read/Grep/Glob 自主检索（tools=READ_ONLY_TOOLS，max_turns=16）。`build_segment_script_context` 的全文产出目前主要供**前端弹窗上下文预览**（`GET /steps/{session_id}/storyboard-segments/{index}/prompt-context`）与 segment_material_match 的 `segment_context` 输入；提示词生成完成后另有轻量 agent run 自动挑选参考素材图（见 prompts 配套）。

## 关键流程

**workspace_sections 共享装配（backend/core/services/workspace_sections.py）**

1. `workspace_section(store, sid, episode_id=None)` — 经 `store.agent_entry(sid)` 取 {available, story_root, map_path}；不可用返回「（剧本工作区不可用）」；输出首两行为工作区根目录与 MAP 路径，episode_id 非空时附「本集分集设计（必读）」路径 + 全剧大纲/实体卡/前后集衔接指引，为空时附全剧目录地图。
2. `load_story_logic` — `store.read_story_logic(sid)` 有值即返回；否则 `sm.get_step_result(sid, 'story_ideation')` 的 `result_data.story_logic`（DB 老数据 fallback）。
3. `get_selected_episode(sm, session_id)` — 读 `select_episode` 步骤 result_data；无步骤或无 result_data 抛 `WorkflowError("会话尚未完成第 1 步：从剧本选集（旧会话不兼容，请从「创作剧本」重新开始）")`。video_workflow（:109）与 storyboard（:103）均经此读取。

**build_segment_script_context（分镜脚本上下文装配，ScriptContextService）**

1. 定位分集 — `store.get_episode(script_session_id, episode_id)` 读 `02-episodes/ep_NN-*.md`；不存在抛 `ValueError("分集不存在: ...")`
2. 段 1 本集全文 — 依次拼 `标题/梗概`、`矛盾链`、`因果链`、`结尾摘要`；`story_progress` 非空时追加 `本集节点进展`（不截断）
3. 段 2 上一集结尾 — `episode_number`（workspace_sections，`ep_01→1`，解析失败返回 10^9 排最后）在 `store.list_episodes` 中找 N-1 集，命中则拼"上一集结尾摘要（本集开场必须自然承接）"，截断 600 字
4. 段 3 实体卡 — `entities = {entity_id: entity}` 索引自 `store.list_entities`；遍历 `character_ids + scene_ids`，`_entity_card` 生成 `- {eid} {name}（人物|场景）：{description}`；eid 以 `chr` 开头判为人物，人物卡再按 MOTIVATION_KEYS 从 `entity.meta` 取非空键拼 `（人物内在动机：性格：…；欲望：…）`（截断 150 字）；每卡截断 280 字
5. 段 4 伏笔关联 — `_build_foreshadow_related`：本集 `foreshadow_refs`/`clue_refs` 的 `entity_id` 并集为 ref_ids；遍历其它集（跳过同集），与其 refs 求 shared 交集；非空则拼一条 `- {episode_id}（{title}）共享伏笔/线索 {eid}（{name}）：该集 {eid}:{action}，本集 {eid}:{action}。{summary}`；summary 取法：其它集序号更小（已播出）用其 `ending_summary`，更大（未播出）用 `logline`；动作对去重排序；单条截断 300 字
6. 段 5 全局大纲 — `load_story_outline`（workspace_sections）读 outline.md mindmap（无则跳过该段），`replace("\n#", " ")` 压平标题后截断 3500 字
7. 各段以 `\n` join 返回

**build_prompt_context 与消费（storyboard.py）**

1. `StoryboardWorkflow.build_prompt_context(session_id, index)` 组装 dict：`episode_title`、`story_outline`（经 `load_story_outline` 读 outline.md mindmap 全文，不截断）、`episode_context`（本服务的 build_segment_script_context）、`video_params`、`segment`、`prev_segment`（index-1）、`reference_images`、`overlap`、`effective_overlap`、`overlap_rule`
2. effective_overlap 规则 — `overlap = int(seg.get("overlap", 1))`；仅当 `index > 0` 且 `seg.mode == "all_reference"` 时生效，否则为 0；overlap_rule 据此生成"接续上一分镜"或"不得出现接续字样"的规则文案
3. 弹窗预览 — `GET /steps/{session_id}/storyboard-segments/{index}/prompt-context`（`backend/api/v1/steps.py`）返回该 dict；前端 `stepApi.getSegmentPromptContext`（`frontend/src/api/client.ts`）→ `StepSegmentManagement.tsx` 提示词生成弹窗以 ContextBlock 展示 `story_outline`（剧本大纲）、`episode_context`（本集脚本/分集设计）、当前分镜内容、参考素材图列表、overlap 衔接信息
4. agent 调用 — `generate_segment_prompt` 复用同一 ctx，但 user_prompt 走渐进式披露：skill 规范必读指引（video-prompt skill 同步进工作区）+ `workspace_section` 剧本工作区段（episode 裁剪视角）+ 视频参数 + 当前分镜/上一分镜/参考素材图 + 衔接规则 + 检索指引；`episode_context`/`story_outline` 不进入 user_prompt

**参考素材图自动匹配（prompts 配套）**

1. `backend/prompts/segment_material_match.md`（新增）— 分镜提示词生成后自动挑选参考素材图：输入 `segment_context` / `segment_prompt` / `candidate_images`（候选素材清单，含缩略图本地路径），输出严格 JSON `{"image_ids": [...]}`（空数组合法，宁缺毋滥）；storyboard.py 约 L784 经 `agent_steps.run`（template='segment_material_match'，system_prompt=SEGMENT_REF_MATCH_SYSTEM）加载执行，LLM 可 Read 候选缩略图看画面（cwd 授予只读工具，max_turns=12）；输出经校验收敛（过滤候选外 ID 防幻觉 → 保序去重 → resolve → 截断 MAX_AUTO_MATCH_REFS 上限）后自动关联当前分镜。
2. `backend/prompts/storyboard_outline.md` — 新增「拍给观众看」约束块（本集是拍给观众看的短剧、不是剧情备忘录——分镜按戏剧节奏导出，不是按事件顺序切出）。
3. system prompt 约束 — `backend/core/agents/system_prompts.py` 的 `SEGMENT_REF_MATCH_SYSTEM`（约 :37，选图助理 + 严格 JSON）与 `SEGMENT_PROMPT_SYSTEM`（纯文本输出 + 工作区检索边界）。

**素材池（MaterialPoolService，backend/core/services/material_pool_service.py，从分镜 agents 层迁入）**

1. `list_pool(script_session_id, episode_id)` — 选择弹窗素材池分组：核心素材组（`_fetch_lookbook_images`：已完成且有 image_path 的核心素材图，映射 `image_id=f"lookbook_{row['image_id']}"`，story 级跨集共享，label「核心素材」）+ 按集分组的分集素材（`list_episode_materials(task_status='completed')`，本集在前、其余按 `episode_number` 排序；不跨 story）。
2. `resolve_pool_image(script_session_id, image_id)` — 素材池 ID 解析：`lookbook_` 前缀走 `scm.get_lookbook`，其余（`mat_*`）走 `scm.get_episode_material`；不存在/跨 story（script_session_id 不匹配）/未生成（无 image_path）抛业务异常（storyboard 注入 StoryboardError）。
3. `validate_reference_paths` — 上传参考图路径校验（resolve 后必须仍在 static/uploads 内，拒绝 `../..` 路径穿越）；`delete_material` — 删分集素材图 DB 记录 + 本地归档文件（http 外链无文件可删；分镜文件中的引用不在清理范围）。

## 涉及代码

- `backend/core/services/workspace_sections.py` — 共享装配：workspace_section / workspace_envelope / episode_number / load_story_logic（DB fallback）/ load_story_outline / get_selected_episode（WorkflowError）
- `backend/core/services/step_payload.py` — 投影读侧（替代已删除的 workspace_projection.py）：script_step_results / video_step_results（注入 comfyui_import 辅助状态）/ script_title；无 DB 旧数据 fallback
- `backend/core/services/script_context_service.py` — `ScriptContextService`：`build_segment_script_context`（5 段装配）、`_build_foreshadow_related`；模块级 `_entity_card`/`_truncate` 与长度常量（episode_number/load_story_outline 已收敛至 workspace_sections）
- `backend/core/services/material_pool_service.py` — 素材池：list_pool / resolve_pool_image / _fetch_lookbook_images / delete_material / validate_reference_paths
- `backend/core/agents/storyboard.py` — 消费方：`build_prompt_context`、`generate_segment_prompt`（渐进式披露 prompt）、segment_material_match 自动匹配（约 L784）、`list_material_pool`（委托 MaterialPoolService）、`_resolve_pool_image`；构造时注入 `ScriptContextService(scm, store)` 与 `MaterialPoolService(store, scm, StoryboardError)`
- `backend/core/workflows/video_workflow.py` — 经 `get_selected_episode`（workspace_sections）读取选集信息
- `backend/core/persistence/workspace_store.py` — 工作区 markdown 权威源：`get_episode`/`list_episodes`（02-episodes/ep_NN-*.md）、`list_entities`（03-entities/）、`read_outline`（01-outline/outline.md）、`read_story_logic`（00-ideation/story-logic.md）、`agent_entry`
- `backend/core/persistence/script_manager.py` — `list_lookbook`（lookbook_images 表过滤）、`get_lookbook`、`get_episode_material`、`list_episode_materials`（素材池数据源）
- `backend/api/v1/steps.py` — `GET /{session_id}/storyboard-segments/{index}/prompt-context`（弹窗上下文预览端点）
- `backend/prompts/segment_material_match.md` / `backend/prompts/storyboard_outline.md` / `backend/core/agents/system_prompts.py` — prompts 配套（自动选图 / 拍给观众看约束 / system 约束）
- `frontend/src/api/client.ts` — `stepApi.getSegmentPromptContext`
- `frontend/src/components/workflow/StepSegmentManagement.tsx` — 提示词生成弹窗：ContextBlock 展示 story_outline/episode_context/当前分镜/参考素材图/overlap 信息

## 相关功能

- 分镜管理（StepSegmentManagement：分镜形式/overlap 配置、参考素材图编辑、提示词生成弹窗 + 自动匹配参考素材图）
- video-prompt skill 提示词生成（渐进式披露：skill 规范 + 工作区自主检索）
- 素材池选择（核心素材 + 本集素材 + 其他集素材，MaterialPoolService）
- 素材库（lookbook library：跨剧本复用已完成核心素材图，见 logics/image-generation-service.md）
- 剧本 4 步工作流（story_ideation → story_outline → episode_design → lookbook_images，产出本服务读取的工作区 markdown 与核心素材图 DB 记录）

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-21 | 装配逻辑收敛至 services 层 — 新增 workspace_sections.py（workspace_section/workspace_envelope/episode_number/load_story_logic 保留 DB fallback/load_story_outline/get_selected_episode 抛 WorkflowError），agents 层本地重复方法删除；投影读侧 workspace_projection.py → step_payload.py（无 DB fallback，视频侧注入 comfyui_import）；ScriptContextService 收敛为纯分镜上下文装配（fetch_lookbook_images 等素材池方法迁至新 MaterialPoolService）；新增 segment_material_match.md 自动匹配参考素材图与 storyboard_outline.md「拍给观众看」约束；术语「定妆照」→「核心素材图」、新增「素材库」 |
