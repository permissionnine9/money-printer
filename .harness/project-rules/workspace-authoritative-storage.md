---
name: workspace-authoritative-storage
摘要: 剧本/分镜 markdown 产物以 workspace/ 文件为唯一权威源，一律经 WorkspaceStore 读写；DB 只留会话状态与任务状态薄数据，投影层回填旧 JSON 形状；迁移永不 DROP 表。
tags: [架构, 存储, workspace, 文件化, 迁移, workspace-store]
---

# workspace 权威存储规范（文件化创作工作区）

**类别:** 实现规范
**最后更新:** 2026-09-19

## 原因

文件化改造后，剧本/分镜的 markdown 类中间产物（故事逻辑/大纲/分集设计/实体卡/分镜）从 SQLite 迁到 `workspace/` 目录的 markdown 文件，**文件是唯一权威源**（backend/core/persistence/workspace_store.py 模块 docstring；backend/deps.py `get_workspace_store` L51-54 注释同义）：

- **人类可读可编辑**：正文为 markdown，关联信息（人物/场景/伏笔引用、时长、overlap、参考图、edited 标志）全部存 frontmatter 元数据。
- **Agent 可检索**：MAP.md 提供目录地图，Agent 在 story 根内用 Read/Grep/Glob 检索（含按实体 ID Grep 伏笔跨集埋设/回收位置）。
- **API 零改动兼容**：store 返回的 dict 键与旧 SQLite row 完全一致（episodes/script_entities 表 → 文件投影零转换），API 层无需改动响应结构。
- **DB 角色收缩**：`ScriptManager`（backend/core/persistence/script_manager.py）只保留生图任务状态机两张表（定妆照/分集素材图）；`script_entities`/`episodes` 两张历史表结构保留仅用于迁移对账，读写已全部切至 `WorkspaceStore`。

## 适用范围

**1. 权威与从属清单 —— 什么进文件、什么留 DB：**

| 数据 | 权威源 | 说明 |
|------|--------|------|
| 故事逻辑 | `workspace/{剧名}-{sid8}/00-ideation/story-logic.md` | `write_story_logic` / `read_story_logic` |
| 全剧大纲 | `01-outline/outline.md` | frontmatter 含 title/edited/requirements |
| 分集设计 | `02-episodes/ep_NN-标题.md` | 正文五节：梗概/矛盾链/因果链/结尾摘要/节点进展 |
| 实体卡 | `03-entities/{chr\|scn\|clu\|fs}_NNN-名字.md` | ID 跨 story 全局唯一 |
| 分镜 | `04-storyboards/ep_NN/vs-{视频会话id前8}/` | storyboard.md 导图 + seg_NN 分镜文件；同分集多次视频会话 = 兄弟 vs 目录 |
| MAP.md | story 根 | 系统自动维护的目录地图，禁止手工编辑 |
| 会话状态/步骤推进 | DB `sessions`/`step_results` | 薄 envelope：`{"_artifact": "workspace", "path": "workspace/..."}` + `_success`/`_cancelled` flags |
| story_ideation 的 messages/agent_session_id | DB | 对话回放与 resume 句柄，非 markdown |
| select_episode / generate_videos | DB | 视频工作流选集与生成记录 |
| 定妆照/分集素材图任务状态 | DB `ScriptManager` 两张表 | 生图任务状态机；实体文件只存 `lookbook_image_id`/`lookbook_image_path` 引用 |

**2. 各层接入点：**

- backend/core/persistence/workspace_store.py —— `WorkspaceStore`（967 行）唯一读写入口；原子写（`_static_write` L304-308：tmp + `os.replace`）+ per-story 可重入锁（`_story_lock` L208-214）+ 实体 ID 全局锁（`_ENTITY_ID_LOCK` L60，跨会话防撞号）。
- backend/core/config.py L18-19 —— `WORKSPACE_DIR = Path(__file__).parent.parent.parent / "workspace"`（项目根 workspace/，导入时 `mkdir` 确保存在）。
- backend/deps.py —— `get_workspace_store()` 为 `lru_cache` 单例，注入 `get_script_session_manager()`（读 workspace_path 锚点）。
- story 目录定位：`sessions.workspace_path` 锚点优先，失效 warning 后 glob `*-{sid8}` 兜底（`story_dir` L216-229）。
- 投影层 backend/core/services/workspace_projection.py（65 行）—— 文件 + DB 薄 envelope → 旧 `step_results` JSON 形状；文件优先，老数据（未导出）fallback 用 DB `result_data`。
- 写侧 Agent：backend/core/agents/script_workflow.py（`write_story_logic` L160-161、`write_outline` L236、薄 envelope `_envelope` L72-76）；backend/core/agents/storyboard.py（`write_storyboard` 调用 L215、薄 envelope `_storyboard_envelope` L99-106）。
- 读侧 API：backend/api/v1/script_sessions.py（`script_step_results` 投影 L114/L244、`script_title` L91）；backend/api/v1/sessions.py（`video_step_results` L155、`script_title` L119-121）。
- 存量迁移：backend/scripts/migrate_db_to_workspace.py（360 行，`--export`/`--verify`/`--cutover`/`--purge-tables`）。
- 回归防线：tests/manual/test_workspace_store.py（346 行 smoke 断言集，`main()` 入口直接 python 运行、`tempfile.mkdtemp` 注入临时目录，非 pytest）。

## 示例

✅ **正确做法:**

**1. markdown 产物一律经 WorkspaceStore 读写（不自造文件路径）**

```python
store = get_workspace_store()          # deps 单例
logic = store.read_story_logic(sid)     # 读
store.write_outline(sid, mindmap, requirements=req)   # 写（剧名取 mindmap 根标题，story 目录随剧名正名）
```

**2. 步骤结果写薄 envelope（内容落文件，DB 行只留定位指针）**

backend/core/agents/script_workflow.py L72-76 的形态：

```python
story = self.store.story_dir(session_id)
base = f"workspace/{story.name}" if story else "workspace"
return {"_artifact": "workspace", "path": f"{base}/{rel}"}   # path 相对项目根
```

**3. 读侧走投影层，形状与旧 step_results 完全一致**

backend/api/v1/script_sessions.py：`script_step_results(sm, get_workspace_store(), session_id)` —— story_logic/story_outline 从文件回填；backend/api/v1/sessions.py：`video_step_results(...)` —— `storyboard_outline` 步骤的 mindmap/segments 从分镜文件回填；`script_title` 文件 outline.title 优先，fallback 解析 DB mindmap。

**4. 迁移与 cutover（backend/scripts/migrate_db_to_workspace.py）**

```bash
.venv/bin/python backend/scripts/migrate_db_to_workspace.py --export   # DB → 文件（幂等）
.venv/bin/python backend/scripts/migrate_db_to_workspace.py --verify   # 逐键对账，差异非零退出
.venv/bin/python backend/scripts/migrate_db_to_workspace.py --cutover [--purge-tables]
```

- `--cutover` 前置检查大纲/实体/分集/分镜文件齐全（`--purge-tables` 会 `DELETE FROM episodes/script_entities`，缺文件即永久丢失，L255-269）。
- cutover 时先备份 `data/sessions.db.bak-{时间戳}`（L286-288），再换薄 envelope，**永不 DROP 表**（只 DELETE 行，L322-326）。
- cutover 后 `_has_content_rows` 检测 DB 无内容行，`--export`/`--verify` 自动停用（L343-352）。

**5. Agent 边界（MAP.md 自动渲染，refresh_map L884-949）**

- Agent 工作目录 = story 根绝对路径（`story_cwd` L273-276，供 run_agent 的 cwd）。
- MAP.md 边界规则（L944-948）：只能在本 story 目录内 Read/Grep/Glob，禁止读取工作区之外路径；**所有产物由系统统一写入，Agent 只具备读权限**。
- prompt 注入用 `agent_entry`（L953-967）：story_root/map_path/map_summary（摘要取「目录结构」一节）。

**6. 级联清理边界（delete_story_content L663-686）**

大纲重生成的级联清理只清空 02-episodes 与 03-entities；**04-storyboards 保留**（视频会话数据不因剧本侧操作被删）；定妆照/素材图任务表在 DB，由调用方另行清理。删除剧本会话时 `delete_story`（L688-698）整树 `rmtree` 并把锚点置 None。

❌ **错误做法:**

- **直接读写 DB 旧表**：`ScriptManager` 的实体/分集读写方法已随文件化改造删除（迁移脚本用原生 SQL 只读对账）；新代码再写 `INSERT INTO episodes` 即产生双权威源。
- **绕过 WorkspaceStore 直接 open/write workspace 文件**：丢失原子写、per-story 锁、MAP 刷新、文件名净化与转义双射，产生并发 lost update 与字段走私。
- **把 markdown 内容塞回 DB result_data**：cutover 后内容行已清，写回 DB 令文件与 DB 分叉。
- **把非 markdown 状态写进文件**：生图任务状态机、对话回放、选集记录始终以 DB 为准；实体文件只存定妆照引用。
- **Agent 在工作流中直接写文件**：MAP.md 边界规则声明 Agent 只读，产物由系统统一写入。
- **cutover 时 DROP 表**：约定永不 DROP，只 DELETE 行 + 事先备份；表结构保留用于对账与回滚。
- **手工编辑 MAP.md**：每次写后由 `_refresh` 惰性全量重渲染，手工改动会被覆盖。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness 文档 pipeline 基于源码分析生成 |
