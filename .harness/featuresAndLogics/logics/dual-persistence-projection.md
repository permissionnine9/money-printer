---
name: 双层持久化与投影逻辑
摘要: workspace 文件为唯一权威源、SQLite 只存薄 envelope，step_payload 读投影 + workspace_sections 装配拆分自已删除的 workspace_projection，ScriptManager 收缩为生图任务状态机。
tags: persistence, workspace, sqlite, migration, projection
---

# 双层持久化与投影逻辑

**最后更新:** 2026-09-21

## 逻辑概述

文件化改造后的持久化分两层：**workspace/ markdown frontmatter 文件是剧本/分镜产物的唯一权威源**（经 WorkspaceStore 读写），SQLite `data/sessions.db` 只保留会话状态、任务状态与薄 envelope（`_artifact: workspace` 指针）。原投影层 `workspace_projection.py`（65 行）已删除，职责拆分为 `backend/core/services/step_payload.py`（读侧投影：API 返回前把文件内容还原成 step_results JSON 形状）与 `backend/core/services/workspace_sections.py`（agents 层装配：收敛此前散落在各 agent 的重复装配逻辑）。读投影**不再有「DB 旧完整数据 fallback」兼容逻辑，文件为唯一权威源**（唯一例外：workspace_sections.load_story_logic 保留 DB fallback）。

## 关键流程

1. **读投影（step_payload.py，48 行）** — `script_step_results(sm, store, session_id)` / `video_step_results(...)` / `script_title(...)`：把 step_results 薄 envelope 还原为旧 JSON 形状供 API 返回；**不再有「DB 旧完整数据 fallback」，文件为唯一权威源**；视频侧扩展——`storyboard_outline` 步骤读分镜文件（先取 `select_episode` 步骤结果的 script_session_id/episode_id 定位 story 树，再 `store.read_storyboard` 还原 mindmap/edited/segments/segment_count）+ 注入 comfyui_import 辅助状态（save_aux_state 落库，见 logics/session-step-state-machine.md）
2. **agents 层装配（workspace_sections.py，83 行）** — 自 agents 层重复装配逻辑收敛：`workspace_section()`（agent prompt 剧本工作区段）、`workspace_envelope()`（薄 envelope `{"_artifact": "workspace", "path": ...}`）、`episode_number()`、`load_story_logic()`（此处保留 DB fallback，唯一例外）、`load_story_outline()`、`get_selected_episode()`（不存在时抛 `WorkflowError`——`backend/core/errors.py` 基类——含旧会话不兼容提示）
3. **消费方更新** — 读侧 `backend/api/v1/sessions.py` / `script_sessions.py` 经 step_payload；写侧 agent（`storyboard.py:84-86` / `script_workflow.py:69-71`）经注入的 workspace_sections 服务
4. **ScriptManager 角色再收缩** — episodes/script_entities 影子表退役（DDL 与读写删除，仅 migrate_db_to_workspace.py 迁移对账维护）；保留两张生图任务状态机表（lookbook_images / episode_material_images）+ 新增 `list_completed_lookbooks` / `insert_lookbook(image_path, meta)` / `delete_script_data(keep_completed_lookbooks)`
5. **级联重生成** — `backend/core/services/regeneration.py` 的 `cascade_regenerate(sm, store, scm, sid, step)`（services 层编排，避免 SessionManager 反向依赖）：`clear_steps_after` → `delete_story_content`（清 02-episodes/03-entities，04-storyboards 保留）→ `delete_script_data(keep_completed_lookbooks=True)`（保留已完成核心素材图进素材库）
6. **标题** — workspace_store 新增 `read_story_title` / `set_story_title`；`step_payload.script_title` 文件 outline.title 优先逻辑保留
7. **迁移三段式**（migrate_db_to_workspace.py）：
   - `--export`：DB step_results/episodes/script_entities → WorkspaceStore markdown（幂等可重跑，导出前先 `delete_story_content` 清文件侧残留）
   - `--verify`：DB ↔ 文件逐键对账（忽略时间戳与 edited 等 `*_IGNORE_KEYS`），差异打印前 50 条并退出码 1
   - `--cutover`：前置完整性检查 → `shutil.copy2` 备份 DB（sessions.db.bak-时间戳）→ step_results 内容行替换为薄 envelope → 可选 `--purge-tables` 清空 episodes/script_entities（**永不 DROP 表**）
8. **留 DB 不迁的数据**：story_ideation 的 agent_session_id/messages、select_episode、generate_videos、lookbook/episode_material 任务表（非 markdown 内容，始终以 DB 为准）
9. **cutover 后自动停用**：`_has_content_rows` 检测 DB 是否仍含完整内容行，无则 export/verify 拒绝执行

## 涉及代码

- `backend/core/services/step_payload.py` — 读投影核心（script_step_results / video_step_results / script_title，形状与旧 get_step_results_map 一致，文件为唯一权威源无 DB fallback）
- `backend/core/services/workspace_sections.py` — agents 层装配（workspace_section / workspace_envelope / episode_number / load_story_logic / load_story_outline / get_selected_episode）
- `backend/core/services/regeneration.py` — cascade_regenerate 级联重生成编排（services 层，避免 SessionManager 反向依赖）
- `backend/scripts/migrate_db_to_workspace.py` — 迁移 CLI（原生 SQL 直读 episodes/script_entities，因 ScriptManager 对应读方法已随文件化删除；DB_PATH 硬编码 `data/sessions.db`；影子表退役后仅迁移对账维护）
- `backend/core/persistence/workspace_store.py` — 权威源读写（read_story_logic/read_outline/read_storyboard/read_story_title/set_story_title）
- `backend/core/persistence/session_manager.py` — step_results 行与薄 envelope 存储（save_aux_state 辅助状态）
- `backend/core/persistence/script_manager.py` — 收缩为两张生图任务状态机表（lookbook_images/episode_material_images）：list_completed_lookbooks / insert_lookbook / delete_script_data(keep_completed_lookbooks)

## 相关功能

- 剧本创作工作流（features/script-workflow.md）
- workspace 文件化存储核心逻辑（logics/workspace-store.md）
- workspace 权威存储规范（project-rules/workspace-authoritative-storage.md）

## 注意事项

- 读投影无 DB 旧完整数据 fallback：老会话若文件侧缺失（未迁移/已删），投影结果即缺失对应内容；`workspace_sections.get_selected_episode` 不存在时抛 WorkflowError 并附旧会话不兼容提示
- `load_story_logic` 是唯一保留 DB fallback 的读取口（workspace_sections 内），step_payload 读投影侧无 fallback
- 投影只覆盖 markdown 类产物（story_logic/story_outline/storyboard_outline）；其余步骤数据原样来自 DB
- `storyboard_outline` 投影依赖 `select_episode` 步骤结果中的 script_session_id/episode_id 定位 story 树
- 级联重生成保留 04-storyboards 与已完成核心素材图（delete_script_data(keep_completed_lookbooks=True)），只清 02-episodes/03-entities 与下游步骤结果
- 迁移脚本约定"时间戳不保真"——文件时间戳自导出时刻起为新的权威
- cutover 备份写同目录 `sessions.db.bak-YYYYmmdd-HHMMSS`，需注意磁盘占用

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-21 | workspace_projection.py 删除并拆分为 step_payload（读投影，去 DB fallback、扩展视频侧）+ workspace_sections（agents 层装配收敛）；ScriptManager 影子表退役收缩为生图任务状态机（含 lookbook 素材库保留）；新增 regeneration.cascade_regenerate；workspace_store 新增 read/set_story_title |
