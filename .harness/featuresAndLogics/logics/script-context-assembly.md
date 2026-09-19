---
name: 剧本上下文装配逻辑
摘要: ScriptContextService 从工作区 markdown 装配分镜上下文（分集设计/实体卡/伏笔关联/大纲摘要），定妆照素材池读 DB
tags: 剧本上下文, ScriptContextService, 分镜提示词, 实体卡, 定妆照, 素材池
---

# 剧本上下文装配逻辑

**最后更新:** 2026-09-19

## 逻辑概述

`ScriptContextService`（`backend/core/services/script_context_service.py`）是剧本侧（4 步剧本会话）到视频侧（V2 4 步视频工作流）的上下文装配器：给定 `(script_session_id, episode_id)`，产出供分镜脚本生成、参考图生成、素材池消费的剧本上下文文本。

数据源分工：markdown 产物（分集设计/实体卡/全剧大纲）以工作区文件为权威源，经 `WorkspaceStore` 读取；定妆照/素材图的任务状态仍读 DB（`ScriptManager`，构造属性名 `scm`）。构造时可注入 `ScriptManager` 与 `WorkspaceStore`（`store` 缺省时延迟导入 `backend.deps.get_workspace_store()` 单例，避免循环依赖）。

`build_segment_script_context` 的装配优先级（各段超长截断，保证 prompt 总量可控）：

1. 本集分集设计全文（标题/梗概/矛盾链/因果链/结尾摘要 + 节点进展 story_progress，全文注入不截断）
2. 上一集结尾摘要（按 `ep_NN` 序号定位 N-1 的相邻集；ep_01 无；截断上限 `RELATED_EPISODE_MAX_CHARS * 2` = 600 字）
3. 本集引用的人物/场景实体卡（`character_ids + scene_ids`；单卡上限 280 字；人物卡附加内在动机摘要，上限 150 字）
4. 伏笔/线索关联集摘要（本集 `foreshadow_refs ∪ clue_refs` 与其它集 refs 求交集反查；单条上限 300 字）
5. 全剧大纲摘要（outline.md 的 mindmap；`\n#` 压平为空格后截断 3500 字，作压缩兜底）

常量（模块级）：`OUTLINE_MAX_CHARS=3500`、`ENTITY_CARD_MAX_CHARS=280`、`RELATED_EPISODE_MAX_CHARS=300`、`MOTIVATION_MAX_CHARS=150`、`MOTIVATION_KEYS=("性格","欲望","身份","伤口")`。`_truncate` 超限时截断并追加 `…（截断）`。

当前消费格局（重要）：分镜提示词生成的 agent prompt 已改为**渐进式披露**——`generate_segment_prompt` 的 user_prompt 不再全文注入 `episode_context`，只注入工作区目录地图 + 检索指引（必读本集分集设计文件、按 frontmatter 的 character_ids/scene_ids Read 实体卡、Grep 伏笔实体 ID、读相邻集文件），由 agent 在剧本目录内用 Read/Grep/Glob 自主检索（tools=READ_ONLY_TOOLS，max_turns=16）。`build_segment_script_context` 的全文产出目前主要供**前端弹窗上下文预览**（`GET /steps/{session_id}/storyboard-segments/{index}/prompt-context`），即装配结果"展示与 agent 调用共用"中的展示侧；素材池/定妆照相关方法则仍在后端主链路使用。

## 关键流程

**build_segment_script_context（分镜脚本上下文装配）**

1. 定位分集 — `store.get_episode(script_session_id, episode_id)` 读 `02-episodes/ep_NN-*.md`；不存在抛 `ValueError("分集不存在: ...")`
2. 段 1 本集全文 — 依次拼 `标题/梗概`、`矛盾链`、`因果链`、`结尾摘要`；`story_progress` 非空时追加 `本集节点进展`（不截断）
3. 段 2 上一集结尾 — `_episode_num`（`ep_01→1`，解析失败返回 0）在 `store.list_episodes` 中找 N-1 集，命中则拼"上一集结尾摘要（本集开场必须自然承接）"，截断 600 字
4. 段 3 实体卡 — `entities = {entity_id: entity}` 索引自 `store.list_entities`；遍历 `character_ids + scene_ids`，`_entity_card` 生成 `- {eid} {name}（人物|场景）：{description}`；eid 以 `chr` 开头判为人物，人物卡再按 MOTIVATION_KEYS 从 `entity.meta` 取非空键拼 `（人物内在动机：性格：…；欲望：…）`（截断 150 字）；每卡截断 280 字
5. 段 4 伏笔关联 — `_build_foreshadow_related`：本集 `foreshadow_refs`/`clue_refs` 的 `entity_id` 并集为 ref_ids；遍历其它集（跳过同集），与其 refs 求 shared 交集；非空则拼一条 `- {episode_id}（{title}）共享伏笔/线索 {eid}（{name}）：该集 {eid}:{action}，本集 {eid}:{action}。{summary}`；summary 取法：其它集序号更小（已播出）用其 `ending_summary`，更大（未播出）用 `logline`；动作对去重排序；单条截断 300 字
6. 段 5 全局大纲 — `store.read_outline(...)` 取 `mindmap`（无则跳过该段），`replace("\n#", " ")` 压平标题后截断 3500 字
7. 各段以 `\n` join 返回

**build_prompt_context 与消费（storyboard.py）**

1. `StoryboardWorkflow.build_prompt_context(session_id, index)` 组装 dict：`episode_title`、`story_outline`（`_load_story_outline` 读 outline.md mindmap 全文，不截断）、`episode_context`（本服务的 build_segment_script_context）、`video_params`、`segment`、`prev_segment`（index-1）、`reference_images`、`overlap`、`effective_overlap`、`overlap_rule`
2. effective_overlap 规则 — `overlap = int(seg.get("overlap", 1))`；仅当 `index > 0` 且 `seg.mode == "all_reference"` 时生效，否则为 0；overlap_rule 据此生成"接续上一分镜"或"不得出现接续字样"的规则文案
3. 弹窗预览 — `GET /steps/{session_id}/storyboard-segments/{index}/prompt-context`（`backend/api/v1/steps.py`）返回该 dict；前端 `stepApi.getSegmentPromptContext`（`frontend/src/api/client.ts`）→ `StepSegmentManagement.tsx` 提示词生成弹窗以 ContextBlock 展示 `story_outline`（剧本大纲）、`episode_context`（本集脚本/分集设计）、当前分镜内容、参考素材图列表、overlap 衔接信息
4. agent 调用 — `generate_segment_prompt` 复用同一 ctx，但 user_prompt 走渐进式披露：skill 规范必读指引（video-prompt skill 同步进工作区）+ `_workspace_section` 剧本工作区目录地图 + 视频参数 + 当前分镜/上一分镜/参考素材图 + 衔接规则 + 检索指引；`episode_context`/`story_outline` 不进入 user_prompt

**参考图与素材池**

1. `build_reference_images_context(script_session_id, episode_id)` — 装配"本集参考图生成"上下文：本集标题行 + 本集实体卡列表（单卡截断 280 字）；已完成定妆照（`scm.list_lookbook(task_status="completed")`）的实体标注"（已有定妆照，勿重复生成）"。**注：当前仓库内该方法无调用方（仅定义），属预留/待接线能力**；分镜脚本部分由调用方另行拼接的约定见 docstring
2. `fetch_lookbook_images(script_session_id)` — 取已完成且有 image_path 的定妆照，映射为素材池形态：`image_id=f"lookbook_{row['image_id']}"`、`image_type='lookbook'`、带 prompt/description/task_id/task_status；被 `StoryboardWorkflow.list_material_pool` 用作素材池"定妆照"组（story 级，跨集共享）
3. `_resolve_pool_image`（storyboard.py）— 借 `self.script_context.scm` 解析素材池 ID：`lookbook_` 前缀走 `scm.get_lookbook`，其余（`mat_*` 分集素材图）走 `scm.get_episode_material`；不存在/跨 story（script_session_id 不匹配）/未生成（无 image_path）抛 `StoryboardError`

## 涉及代码

- `backend/core/services/script_context_service.py` — `ScriptContextService`：`build_segment_script_context`（5 段装配）、`build_reference_images_context`（预留，无调用方）、`fetch_lookbook_images`（定妆照 → 素材池形态）、`_build_foreshadow_related`、`_load_outline`；模块级 `_episode_num`/`_entity_card`/`_truncate` 与长度常量
- `backend/core/agents/storyboard.py` — 消费方：`build_prompt_context`（episode_context/story_outline 组装）、`generate_segment_prompt`（渐进式披露 prompt）、`list_material_pool`（fetch_lookbook_images 定妆照组）、`_resolve_pool_image`（借 script_context.scm 解析素材池 ID）；构造时 `ScriptContextService(store=store)` 注入同一 WorkspaceStore
- `backend/core/agents/workflow_v2.py` — `VideoCreationWorkflowV2.__init__` 持有 `self.script_context = ScriptContextService()` 实例，但类内未直接调用其方法（实际消费在 storyboard.py）
- `backend/core/persistence/workspace_store.py` — 工作区 markdown 权威源：`get_episode`/`list_episodes`（02-episodes/ep_NN-*.md）、`list_entities`（03-entities/）、`read_outline`（01-outline/outline.md，返回 mindmap/title/edited/requirements）
- `backend/core/persistence/script_manager.py` — `list_lookbook`（lookbook_images 表，按 script_session_id/entity_id/task_status 过滤，created_at 升序）、`get_lookbook`、`get_episode_material`、`list_episode_materials`
- `backend/api/v1/steps.py` — `GET /{session_id}/storyboard-segments/{index}/prompt-context`（get_segment_prompt_context，弹窗上下文预览端点）
- `backend/api/v1/script_sessions.py` — 剧本侧定妆照链路入口（`POST /{session_id}/lookbook/generate` 等，产出写入 lookbook_images 表，供本服务读取）
- `frontend/src/api/client.ts` — `stepApi.getSegmentPromptContext`
- `frontend/src/components/workflow/StepSegmentManagement.tsx` — 提示词生成弹窗：ContextBlock 展示 story_outline/episode_context/当前分镜/参考素材图/overlap 信息
- `backend/deps.py` — `get_workspace_store()`（store 缺省注入源）

## 相关功能

- 分镜管理（StepSegmentManagement：分镜形式/overlap 配置、参考素材图编辑、提示词生成弹窗）
- video-prompt skill 提示词生成（渐进式披露：skill 规范 + 工作区自主检索）
- 素材池选择（定妆照 + 本集素材 + 其他集素材）
- 剧本 4 步工作流（story_ideation → story_outline → episode_design → lookbook_images，产出本服务读取的工作区 markdown 与定妆照 DB 记录）
