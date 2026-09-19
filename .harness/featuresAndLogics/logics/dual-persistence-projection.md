---
name: 双层持久化与投影逻辑
摘要: workspace 文件为权威源、SQLite 只存薄 envelope，投影层还原旧 step_results 形状，迁移脚本三段式 cutover。
tags: persistence, workspace, sqlite, migration, projection
---

# 双层持久化与投影逻辑

**最后更新:** 2026-09-19

## 逻辑概述

文件化改造后的持久化分两层：**workspace/ markdown frontmatter 文件是剧本/分镜产物的唯一权威源**（经 WorkspaceStore 读写），SQLite `data/sessions.db` 只保留会话状态、任务状态与薄 envelope（`_artifact: workspace` 指针）。投影层（workspace_projection.py）在 API 返回前把文件内容还原成旧 step_results JSON 形状，保持前后端兼容；DB 中未迁移的老数据作为 fallback。

## 关键流程

1. **读投影（剧本）** — `script_step_results(sm, store, session_id)`（workspace_projection.py:12）：遍历 `sm.get_step_results_map`，`story_ideation` 步骤用 `store.read_story_logic` 覆盖 story_logic（文件优先，读不到 fallback DB `rd.get("story_logic")`）；`story_outline` 步骤用 `store.read_outline` 的 mindmap/edited/requirements 整体覆盖
2. **读投影（视频）** — `video_step_results`（workspace_projection.py:44）：仅 `storyboard_outline` 步骤被覆盖——先取 `select_episode` 步骤结果拿到 script_session_id/episode_id，再 `store.read_storyboard` 还原 mindmap/edited/segments/segment_count
3. **标题投影** — `script_title`（workspace_projection.py:36）：文件 outline.title 优先，fallback `sm.get_script_title`（解析 DB mindmap）
4. **迁移三段式**（migrate_db_to_workspace.py）：
   - `--export`：DB step_results/episodes/script_entities → WorkspaceStore markdown（幂等可重跑，导出前先 `delete_story_content` 清文件侧残留）
   - `--verify`：DB ↔ 文件逐键对账（忽略时间戳与 edited 等 `*_IGNORE_KEYS`），差异打印前 50 条并退出码 1
   - `--cutover`：前置完整性检查 → `shutil.copy2` 备份 DB（sessions.db.bak-时间戳）→ step_results 内容行替换为薄 envelope → 可选 `--purge-tables` 清空 episodes/script_entities（**永不 DROP 表**）
5. **留 DB 不迁的数据**：story_ideation 的 agent_session_id/messages、select_episode、generate_videos、lookbook/episode_material 任务表（非 markdown 内容，始终以 DB 为准）
6. **cutover 后自动停用**：`_has_content_rows` 检测 DB 是否仍含完整内容行，无则 export/verify 拒绝执行

## 涉及代码

- `backend/core/services/workspace_projection.py` — 投影层核心（3 个函数，形状与旧 get_step_results_map 完全一致）
- `backend/scripts/migrate_db_to_workspace.py` — 迁移 CLI（原生 SQL 直读 episodes/script_entities，因 ScriptManager 对应读方法已随文件化删除；DB_PATH 硬编码 `data/sessions.db`）
- `backend/core/persistence/workspace_store.py` — 权威源读写（read_story_logic/read_outline/read_storyboard）
- `backend/core/persistence/session_manager.py` — step_results 行与薄 envelope 存储

## 相关功能

- 剧本创作工作流（features/script-workflow.md）
- workspace 文件化存储核心逻辑（logics/workspace-store.md）
- workspace 权威存储规范（project-rules/workspace-authoritative-storage.md）

## 注意事项

- 投影只覆盖 markdown 类产物（story_logic/story_outline/storyboard_outline）；其余步骤数据原样来自 DB
- `storyboard_outline` 投影依赖 `select_episode` 步骤结果中的 script_session_id/episode_id 定位 story 树
- 迁移脚本约定"时间戳不保真"——文件时间戳自导出时刻起为新的权威
- cutover 备份写同目录 `sessions.db.bak-YYYYmmdd-HHMMSS`，需注意磁盘占用

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
