---
name: workspace-authoritative-storage
摘要: 剧本/分镜 markdown 产物以 workspace/ 文件为唯一权威源，一律经 WorkspaceStore 读写；DB 只留会话状态与生图任务状态机，投影层（step_payload.py + workspace_sections.py）回填旧 JSON 形状且无 DB fallback；episodes/script_entities 影子表退役；核心素材图沉淀素材库跨剧本复用；迁移永不 DROP 表。
tags: [架构, 存储, workspace, 文件化, 迁移, workspace-store, 素材库, 核心素材图]
---

# workspace 权威存储规范（文件化创作工作区）

**类别:** 实现规范
**最后更新:** 2026-09-21

## 原因

文件化改造后，剧本/分镜的 markdown 类中间产物（故事逻辑/大纲/分集设计/实体卡/分镜）从 SQLite 迁到 `workspace/` 目录的 markdown 文件，**文件是唯一权威源**（backend/core/persistence/workspace_store.py 模块 docstring；backend/deps.py `get_workspace_store` 注释同义）：

- **人类可读可编辑**：正文为 markdown，关联信息（人物/场景/伏笔引用、时长、overlap、参考图、edited 标志）全部存 frontmatter 元数据。
- **Agent 可检索**：MAP.md 提供目录地图，Agent 在 story 根内用 Read/Grep/Glob 检索（含按实体 ID Grep 伏笔跨集埋设/回收位置）。
- **API 零改动兼容**：store 返回的 dict 键与旧 SQLite row 完全一致（历史 episodes/script_entities 表 → 文件投影零转换），API 层无需改动响应结构。
- **DB 角色再收缩**：`ScriptManager`（backend/core/persistence/script_manager.py）只保留生图任务状态机两张表（核心素材图/分集素材图，原「定妆照」现称「核心素材图」）+ 素材库查询；**`episodes`/`script_entities` 两张影子表已退役**（DDL 与读写删除，仅 backend/scripts/migrate_db_to_workspace.py 迁移对账继续维护），读写全部走 `WorkspaceStore`。
- **素材库（lookbook library）**：已完成且有图的核心素材图行沉淀为跨剧本复用的历史素材，导入即复制行引用同一远程 URL，不搬文件。

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
| 核心素材图/分集素材图任务状态 | DB `ScriptManager` 两张表 | 生图任务状态机；实体文件只存 `lookbook_image_id`/`lookbook_image_path` 引用；已完成有图的核心素材图行可保留作素材库历史素材 |

**2. 各层接入点：**

- backend/core/persistence/workspace_store.py —— `WorkspaceStore` 唯一读写入口；原子写（`_static_write`：tmp + `os.replace`）+ per-story 可重入锁（`_story_lock`）+ 实体 ID 全局锁（`_ENTITY_ID_LOCK`，跨会话防撞号）。
- backend/core/config.py —— `WORKSPACE_DIR = Path(__file__).parent.parent.parent / "workspace"`（项目根 workspace/，导入时 `mkdir` 确保存在）。
- backend/deps.py —— `get_workspace_store()` 为 `lru_cache` 单例，注入 `get_script_session_manager()`（读 workspace_path 锚点）。
- story 目录定位：`sessions.workspace_path` 锚点优先，失效 warning 后 glob `*-{sid8}` 兜底（`story_dir`）。
- **投影层（原 workspace_projection.py 已删除，职责拆分为两个 service）**：
  - **backend/core/services/step_payload.py**（48 行）：`script_step_results` / `video_step_results` / `script_title` —— 文件 → 旧 `step_results` JSON 形状；**不再有 DB 旧完整数据 fallback，文件为唯一权威源**；视频侧 `storyboard_outline` 步骤读分镜文件回填 mindmap/segments，并注入 comfyui_import 辅助状态。
  - **backend/core/services/workspace_sections.py**（83 行）：`workspace_section` / `workspace_envelope`（薄 envelope 构造）、`episode_number`、`load_story_logic`（**此处保留 DB fallback**，兼容未导出的老会话）、`load_story_outline`、`get_selected_episode`（不存在抛 `WorkflowError`，错误信息含旧会话不兼容提示）。
- 写侧 Agent：backend/core/agents/script_workflow.py（L69-71 注入 service，经 workspace_sections 的 `workspace_section`/`workspace_envelope` 落薄 envelope）；backend/core/agents/storyboard.py（L84-86 同）。
- 读侧 API：backend/api/v1/script_sessions.py 与 backend/api/v1/sessions.py 均经 **step_payload**（`script_step_results` / `video_step_results` / `script_title`）。
- **ScriptManager 影子表退役后的新接口**：`list_completed_lookbooks`（全局 completed 且 image_path 非空行，供素材库列举）；`insert_lookbook` 新增 `image_path`/`meta` 参数；`delete_script_data` 新增 `keep_completed_lookbooks` 参数（True 时保留已完成有图行作素材库历史素材，分集素材图两种模式都全删）。
- **级联清理**：backend/core/services/regeneration.py 的 `cascade_regenerate(sm, store, scm, sid, step)` —— clear_steps_after 清下游步骤 → `store.delete_story_content` 清分集/实体文件 → `scm.delete_script_data(keep_completed_lookbooks=True)` 保留已完成核心素材图进素材库（**04-storyboards 仍保留不变**）。
- **素材库**：backend/core/services/lookbook_library_service.py —— `list_lookbook_library`（按存活 script 会话过滤孤儿行、当前会话组排第一）；`import_lookbook_from_library`（复制源行为新 completed 行、引用同一远程 URL、meta 记 `imported_from{image_id, script_session_id, entity_id}`、`set_entity_lookbook` 回写实体锚点、失败回滚删除复制行）。
- 存量迁移：backend/scripts/migrate_db_to_workspace.py（`--export`/`--verify`/`--cutover`/`--purge-tables`；现为唯一继续触碰 episodes/script_entities 的代码，原生 SQL 只读对账）。
- 回归防线：tests/manual/（文件化架构下 smoke 断言集，直接 python 运行、非 pytest；含 test_workspace_store.py、test_lookbook_library.py 等）。

## 示例

✅ **正确做法:**

**1. markdown 产物一律经 WorkspaceStore 读写（不自造文件路径）**

```python
store = get_workspace_store()          # deps 单例
logic = store.read_story_logic(sid)     # 读
store.write_outline(sid, mindmap, requirements=req)   # 写（剧名取 mindmap 根标题，story 目录随剧名正名）
```

**2. 步骤结果写薄 envelope（内容落文件，DB 行只留定位指针）**

backend/core/agents/script_workflow.py L69-71 注入 service 后经 workspace_sections 的形态：

```python
story = self.store.story_dir(session_id)
base = f"workspace/{story.name}" if story else "workspace"
return {"_artifact": "workspace", "path": f"{base}/{rel}"}   # path 相对项目根
```

**3. 读侧走投影层，形状与旧 step_results 完全一致**

backend/api/v1/script_sessions.py：`script_step_results(...)`（step_payload.py）—— story_logic/story_outline 从文件回填；backend/api/v1/sessions.py：`video_step_results(...)` —— `storyboard_outline` 步骤的 mindmap/segments 从分镜文件回填并注入 comfyui_import 辅助状态；`script_title` 文件 outline.title 优先。**投影层无 DB 旧完整数据 fallback，文件为唯一权威源**（仅 load_story_logic 保留 DB fallback 兼容老会话）。

**4. 迁移与 cutover（backend/scripts/migrate_db_to_workspace.py）**

```bash
.venv/bin/python backend/scripts/migrate_db_to_workspace.py --export   # DB → 文件（幂等）
.venv/bin/python backend/scripts/migrate_db_to_workspace.py --verify   # 逐键对账，差异非零退出
.venv/bin/python backend/scripts/migrate_db_to_workspace.py --cutover [--purge-tables]
```

- `--cutover` 前置检查大纲/实体/分集/分镜文件齐全（`--purge-tables` 会 `DELETE FROM episodes/script_entities`，缺文件即永久丢失）。
- cutover 时先备份 `data/sessions.db.bak-{时间戳}`，再换薄 envelope，**永不 DROP 表**（只 DELETE 行）。
- cutover 后 `_has_content_rows` 检测 DB 无内容行，`--export`/`--verify` 自动停用。

**5. Agent 边界（MAP.md 自动渲染，refresh_map）**

- Agent 工作目录 = story 根绝对路径（`story_cwd`，供 run_agent 的 cwd）。
- MAP.md 边界规则：只能在本 story 目录内 Read/Grep/Glob，禁止读取工作区之外路径；**所有产物由系统统一写入，Agent 只具备读权限**。
- prompt 注入用 `agent_entry`：story_root/map_path/map_summary（摘要取「目录结构」一节）。

**6. 级联清理边界（regeneration.cascade_regenerate）**

大纲重生成的级联链：clear_steps_after 清下游步骤 → `store.delete_story_content` 清 02-episodes 与 03-entities（**04-storyboards 保留**，视频会话数据不因剧本侧操作被删）→ `scm.delete_script_data(keep_completed_lookbooks=True)` 保留已完成核心素材图行进素材库（分集素材图两种模式都全删）。删除剧本会话时 `delete_story` 整树 `rmtree` 并把锚点置 None。

**7. 素材库复用（lookbook_library_service）**

- 列举：`list_lookbook_library` 只按存活 script 会话过滤孤儿行，当前会话组排第一。
- 导入：`import_lookbook_from_library` 复制源行为新 completed 行、引用**同一远程 URL**（不搬文件），meta 记 `imported_from{image_id, script_session_id, entity_id}`，再 `set_entity_lookbook` 回写实体锚点；失败回滚删除复制行。

❌ **错误做法:**

- **引用已删除的 workspace_projection.py**：投影层已拆分为 step_payload.py（读侧回填）+ workspace_sections.py（写侧 envelope 与读取辅助）。
- **直接读写已退役的 episodes/script_entities 影子表**：DDL 与读写已从 ScriptManager 删除（仅迁移脚本用原生 SQL 只读对账）；新代码再写 `INSERT INTO episodes` 即产生双权威源。
- **绕过 WorkspaceStore 直接 open/write workspace 文件**：丢失原子写、per-story 锁、MAP 刷新、文件名净化与转义双射，产生并发 lost update 与字段走私。
- **把 markdown 内容塞回 DB result_data**：cutover 后内容行已清，写回 DB 令文件与 DB 分叉；投影层也无 DB fallback 兜底。
- **把非 markdown 状态写进文件**：生图任务状态机、对话回放、选集记录始终以 DB 为准；实体文件只存核心素材图引用。
- **Agent 在工作流中直接写文件**：MAP.md 边界规则声明 Agent 只读，产物由系统统一写入。
- **cutover 时 DROP 表**：约定永不 DROP，只 DELETE 行 + 事先备份；表结构保留用于对账与回滚。
- **手工编辑 MAP.md**：每次写后由 `_refresh` 惰性全量重渲染，手工改动会被覆盖。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness 文档 pipeline 基于源码分析生成 |
| 2026-09-21 | 迭代修订 — 投影层 workspace_projection.py（65 行）删除，拆分为 step_payload.py（48 行，无 DB 完整数据 fallback，文件唯一权威；storyboard_outline 注入 comfyui_import）+ workspace_sections.py（83 行，envelope/读取辅助，load_story_logic 保留 DB fallback，get_selected_episode 抛 WorkflowError）；ScriptManager 的 episodes/script_entities 影子表退役（DDL 与读写删除，仅迁移脚本维护），新增 list_completed_lookbooks / insert_lookbook(image_path, meta) / delete_script_data(keep_completed_lookbooks)；级联清理改经 regeneration.cascade_regenerate（保留核心素材图进素材库，04-storyboards 不动）；新增素材库服务 lookbook_library_service.py；写侧接入点行号更新（storyboard.py:84-86 / script_workflow.py:69-71）；术语「定妆照」改「核心素材图」 |
