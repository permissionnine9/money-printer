---
name: 剧本实体库管理
摘要: 剧本工作流的全局实体（人物 chr/场景 scn/线索 clu/伏笔 fs）以 markdown 文件为权威数据源，经 /api/v1/script-sessions/{id}/entities 提供增删改查与引用反查，agent 分集设计时经 MCP 工具注册，分集引用其 ID 并做严格校验。
tags: 实体管理, 后端API, 文件化存储, Agent MCP, 前端组件
---

# 剧本实体库管理

**状态:** 已完成
**最后更新:** 2026-09-19

## 功能概述

实体（entity）是剧本工作流的全局复用单元，共 4 类：`character` 人物（ID 前缀 `chr`）、`scene` 场景（`scn`）、`clue` 线索（`clu`）、`foreshadow` 伏笔（`fs`）。每条实体包含名称、视觉描述（正文）、meta 附加信息（性格/欲望/埋设意图等）与定妆照引用；实体 ID 形如 `chr_001`、`fs_012`，跨全部剧本会话全局唯一分配。

实体在第 3 步「分集设计」中由 agent 通过 MCP 写侧工具（`upsert_character/scene/clue/foreshadow`）注册，分集通过 `character_ids/scene_ids/clue_refs/foreshadow_refs` 字段引用实体 ID，保存时经 `_validate_episode_refs` 严格校验（引用存在、类型前缀匹配、action 合法、伏笔 payoff 晚于 plant、线索 reveal 前置、末集未回收伏笔检查）。

存储为文件化改造后的 markdown 权威数据源：每剧本会话一棵 story 树，实体卡存于 `workspace/{剧名}-{会话id前8}/03-entities/{前缀}_NNN-名字.md`，frontmatter 存元数据、正文存 description；返回 dict 的键与旧 SQLite `script_entities` 表行完全一致（文件投影零转换，API 响应结构无需改动）。

整体数据流：agent MCP 工具 / REST API → WorkspaceStore.upsert_entity（锁 + 原子写 md）→ 前端 entityApi.list（StepEpisodeDesign 实体库面板 / StepLookbook 定妆照勾选）→ entityApi.getReferences 引用反查。

## 核心代码路径

- `backend/api/v1/script_sessions.py` — API 层：`/api/v1/script-sessions/{session_id}/entities` 下 5 条路由（列表/新增/更新/引用反查/删除，第 329 行起「实体库」分节），实体 ID 路径参数经 `ENTITY_ID_PATH`（FastAPI Path pattern）格式校验
- `backend/schemas/script.py` — 请求/响应模型：`EntityUpsertRequest`（第 60 行，entity_type 正则限定四类、name 非空）、`EntityReferenceEpisode`/`EntityReferencesResponse`（第 67/73 行）
- `backend/core/persistence/workspace_store.py` — 持久层：实体注册表读写（第 388 行起），ID 前缀映射 `ENTITY_ID_PREFIXES`（第 62 行）、ID 白名单正则（第 44 行）、全局 ID 分配锁 `_ENTITY_ID_LOCK`（第 60 行）、`upsert_entity`/`get_entity`/`list_entities`/`delete_entity`/`set_entity_lookbook`
- `backend/core/agents/script_workflow.py` — Agent 侧：`_build_design_mcp_server`（第 395 行）动态生成 4 个 `upsert_{entity_type}` MCP 工具；`_validate_episode`/`_validate_episode_refs`（第 266/319 行）分集引用校验；`generate_lookbook` 完成后经 `set_entity_lookbook` 回写定妆照引用（第 706/743 行）
- `frontend/src/api/client.ts` — 前端 API client：`entityApi`（第 462 行）仅 `list` 与 `getReferences` 两个方法
- `frontend/src/components/script/StepEpisodeDesign.tsx` — 第 3 步分集设计页的实体库面板：分组展示、卡片展开懒加载引用集、单集详情/编辑表单中的实体引用渲染与编辑
- `frontend/src/components/script/StepLookbook.tsx` — 第 4 步定妆照页：按实体勾选生成定妆照、展示 `lookbook_image_path` 缩略图
- `frontend/src/types/index.ts` — TS 类型：`EntityType`（第 43 行）、`ScriptEntity`（第 45 行）、`EntityRef`（第 59 行，action 四值）、`EntityReferences`（第 71 行）
- `backend/scripts/migrate_db_to_workspace.py` — DB→文件迁移：用 `upsert_entity(create_if_missing=True)` 按原 ID 直接落盘（第 112 行）并回写定妆照引用（第 118 行）
- `backend/deps.py` — 依赖注入：`get_workspace_store()`（第 51 行，`@lru_cache` 单例，注入剧本 SessionManager 用于 workspace_path 锚点）

## 关键逻辑说明

### 后端 API 层（backend/api/v1/script_sessions.py，挂载前缀 /api/v1/script-sessions）

| 路由 | 处理函数 | 行为 |
|------|---------|------|
| GET /{session_id}/entities?entity_type= | list_entities | 可选按类型过滤；返回 `{success, data:{entities, total}}` |
| POST /{session_id}/entities | upsert_entity | 人工新增（ID 由后端分配）；ValueError → 400 |
| PUT /{session_id}/entities/{entity_id} | update_entity | 先 get_entity 判存在（无 → 404 `实体不存在或不属于该会话`）；ValueError → 400 |
| GET /{session_id}/entities/{entity_id}/references | get_entity_references | 引用反查：遍历全部分集，人物/场景按 character_ids/scene_ids 命中给 `出场`，线索/伏笔取 refs 中匹配的 action 值；返回 `{entity_id, episodes:[{episode_id,title,actions}]}` |
| DELETE /{session_id}/entities/{entity_id} | delete_entity | 不存在 → 404；被任一分集引用（character_ids+scene_ids+clue_refs+foreshadow_refs 的 entity_id）→ 400 `先移除引用再删除`；成功返回 `{success, message}` |

所有路由共用 `load_script_session` 依赖（会话不存在 404、非剧本会话 400）。`ENTITY_ID_PATH = Path(pattern=ENTITY_ID_PATTERN)`，路径参数不匹配 `^(chr|scn|clu|fs)_[0-9]{3,}$` 时由 FastAPI 直接 422。`EntityUpsertRequest` 字段：`entity_type`（正则 `^(character|scene|clue|foreshadow)$`）、`name`（min_length=1）、`description`（默认 ''）、`meta`（dict，默认 {}）。

### 持久层（backend/core/persistence/workspace_store.py，文件权威数据源）

- 目录与文件：story 树 `workspace/{剧名}-{sid8}/03-entities/`（`DIR_ENTITIES = "03-entities"`），文件名 `{entity_id}-{净化名}.md`（`sanitize_name`，max_len=30）；story 目录定位锚点（sessions.workspace_path）优先、glob `*-{sid8}` 兜底。
- 文件格式：frontmatter 存 `entity_id/script_session_id/entity_type/name/meta/lookbook_image_id/lookbook_image_path/created_at/updated_at`，正文即 description；`_entity_from_doc` 把文件投影回旧 `script_entities` 行形状（零转换）。
- ID 分配：`_scan_next_entity_id` 跨全工作区 glob `*/03-entities/{前缀}_*.md` 取 MAX+1（`{前缀}_{N:03d}` 零填充 3 位）；新建的「分配 + 落盘」在模块级 `_ENTITY_ID_LOCK` + per-story RLock 内原子完成（防跨会话并发撞号）；`next_entity_id` 仅预览用途。
- `upsert_entity(session_id, entity_type, name, description, meta, entity_id=None, create_if_missing=False)`：entity_type 不在四类 → ValueError；带 entity_id 但文件不存在默认 ValueError（agent 自纠），`create_if_missing=True` 仅供迁移路径；更新时保留旧 meta（新 meta 为空 dict 时回退）、旧 lookbook 引用与 created_at，刷新 updated_at。注意 meta 回退规则：`meta or old_meta.get("meta") or {}`，API 传空 dict 无法清空已有 meta。
- `list_entities(entity_type=None)`：按前缀 glob 过滤，排序 `(entity_type, entity_id)` ASC（与旧 DB 一致）；`get_entity`/`delete_entity` 限定本 story（ID 全局唯一但写/删不得跨会话）。
- `set_entity_lookbook`：定妆照生成完成后回写 `lookbook_image_id/lookbook_image_path` 到 frontmatter（定妆照任务本体仍在 DB，文件只存引用）。
- 安全与并发：ID 先过 `_ENTITY_ID_RE` 白名单（`[0-9]` 显式 ASCII、`\Z` 绝对锚定）再拼 glob，防元字符注入（如 `entity_id="*"` 会误匹配并触发覆写）；写文件为 tmp + `os.replace` 原子写，per-story 可重入锁防并发 lost update。

### Agent 侧注册与引用校验（backend/core/agents/script_workflow.py）

- `_build_design_mcp_server` 内 `def _upsert(entity_type)` 循环生成 4 个 MCP 工具 `upsert_character/scene/clue/foreshadow`（参数 name 必填、description 供生图 80 字内、meta 任意附加、entity_id 更新时传入），直接调 `store.upsert_entity`；即实体注册发生在 agent 分集设计过程中，而非前端表单。
- 分集保存（MCP `save_episode` → `_validate_episode`）与人工编辑（API `update_episode_fields`）共用 `_validate_episode_refs`：引用存在 + 类型前缀匹配（chr/scn/clu/fs）、action ∈ plant/develop/reveal/payoff、伏笔 payoff 集号必须晚于 plant、线索 reveal 前必须有更早集的 plant/develop。
- 末集未回收伏笔检查（已 plant 从未 payoff 必须补 payoff，实体 meta 标记 `open_ending=true` 豁免）位于 `_validate_episode` 尾部，仅 MCP `save_episode` 全量校验路径触发；人工编辑 `update_episode_fields` 只走 `_validate_episode_refs`，不触发该检查与集号连续/每集至少 1 人物 1 场景等全量约束。
- 删除保护分层：store 层 `delete_entity` 不校验引用，反向引用检查在 API 路由层完成（见上表）。

### 前端（frontend/src）

- `entityApi`（client.ts 第 462 行）：`list(sessionId, entityType?)` → GET entities（可选 entity_type 参数）、`getReferences(sessionId, entityId)` → GET references；前端未调用 POST/PUT/DELETE 实体接口（见注意事项）。
- `StepEpisodeDesign.tsx`：实体按 characters/scenes/refEntities（线索+伏笔）三组渲染卡片（第 304-308 行）；卡片展示 name、entity_id Tag、定妆照缩略图（`lookbook_image_path` 有值时）、description、meta 键值；点击展开时懒加载 `getReferences`（第 150 行 loadReferences）渲染「引用集」——线索/伏笔按集排序展示 plant→payoff 时间线（Tag 颜色 payoff=green、plant=orange、其余 blue），人物/场景展示分集列表；agent 运行期间 2s 轮询刷新实体列表。单集编辑表单以 Select（`ep_NN 名字`）编辑 character_ids/scene_ids 与线索/伏笔 refs（实体 + action 两级 Select）。
- `StepLookbook.tsx`：`entityApi.list` 拉全量实体渲染卡片，按实体生成/重生成定妆照，2s 轮询回刷实体与图片。
- `frontend/src/utils/scriptMarkdown.ts`：`buildScriptMarkdown(episodes, entities, outline)` 用实体名把分集 refs 渲染成导出 markdown 的「出场人物/出场场景/线索/伏笔」小节。

## 依赖与复用关系

- 依赖: FastAPI Path pattern 校验（ENTITY_ID_PATH）、pydantic（EntityUpsertRequest 等）、WorkspaceStore（python-frontmatter 库、`backend/core/config.py` 的 WORKSPACE_DIR、`backend/core/utils/image_store.sanitize_name`）、deps.get_workspace_store（lru_cache 单例，注入剧本 SessionManager 读 workspace_path 锚点）、load_script_session 依赖、前端 antd（Card/Tag/Select/Spin）、axios client（baseURL /api/v1）、@/types 的 ScriptEntity/EntityRef/EntityReferences
- 被依赖: 分集设计（episodes 的 character_ids/scene_ids/clue_refs/foreshadow_refs 引用实体 ID）、定妆照生成（script_workflow.generate_lookbook → set_entity_lookbook 回写）、前端 StepEpisodeDesign/StepLookbook/scriptMarkdown、DB→文件迁移脚本 migrate_db_to_workspace.py、delete_story_content（清理 03-entities 目录并计数）
- 可复用组件: WorkspaceStore 的 markdown 文档读写底座（_read_doc/_write_doc/_replace_doc_file、原子写 + per-story 锁）被分集/分镜/大纲等全部 story 产物共用；「ID 白名单正则 + glob 防注入」模式同样用于 episode_id

## 注意事项

- **前端无实体增删改入口**：entityApi 仅有 list/getReferences，POST/PUT/DELETE 三条实体路由后端已实现但前端未调用；实体的实际创建/更新由 agent 在分集设计中经 MCP 工具完成，删除保护（被引用即 400）目前只能经 API 手工触发。
- **ID 全局唯一但写删限本会话**：ID 分配跨全部 story 全局 MAX+1（进程级锁），`_find_entity_file` 只在本 story 目录内查找，跨会话传他人 entity_id 表现为「不存在」。
- **meta 空值不可清空**：update 时新 meta 为 falsy（API 默认 {}）会回退旧 meta，需传非空 dict 才能覆盖。
- **引用完整性靠两层校验**：分集侧保存/编辑时正向校验（引用必须存在且类型匹配），实体侧删除时反向校验（被引用即拒绝）；先有分集引用后有实体删除的窗口由反向校验兜底，反序（引用不存在的实体）由正向校验兜底。
- **glob 注入防护**：entity_id/episode_id 直接拼 glob 与文件路径，必须过 `_ENTITY_ID_RE`/`_EPISODE_ID_RE` 白名单（ASCII 数字 + 绝对锚定）；API 层 pydantic/FastAPI Path 的 pattern 与 Python re 语义已对齐（rust regex 引擎）。
- **定妆照引用双写**：定妆照任务行存 DB（script_manager），实体文件 frontmatter 只存 `lookbook_image_id/path` 引用，二者经 set_entity_lookbook 同步；手工删除图片行不会自动清实体引用（前端展示时按 image_id 匹配、缺失则回退最新一条）。
- **旧 SQLite 语义兼容**：实体文件投影的 dict 键与旧 `script_entities` 表行完全一致，list 排序（entity_type, entity_id ASC）也与旧 DB 一致；迁移脚本按原 ID 直接落盘，不重新分配。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析生成（文件化改造后的实体注册表） |
