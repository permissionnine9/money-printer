---
name: 文件化工作区存储逻辑
摘要: WorkspaceStore 以 markdown+frontmatter 文件树作为剧本/分镜产物权威源，原子写+双锁并发防护，返回 dict 与旧 SQLite row 形状一致
tags: WorkspaceStore, workspace, frontmatter, markdown, 持久化, 并发锁, MAP.md
---

# 文件化工作区存储逻辑

**最后更新:** 2026-09-19

## 逻辑概述

`backend/core/persistence/workspace_store.py` 是剧本/分镜中间产物的 markdown 权威数据源：每个剧本会话一棵 story 树（视频会话不建树，分镜挂在对应分集下的 vs 目录），故事逻辑/全剧大纲/分集设计/实体卡/分镜全部落盘为 frontmatter + markdown 正文文件，人类可直接阅读编辑。关联信息（实体引用、时长、overlap、参考图、edited 标志）存 frontmatter 元数据，正文承载自由文本。

三个核心设计：

1. **零转换投影** — 所有读方法返回 dict 的键与旧 SQLite row 完全一致（episodes/script_entities 表 → 文件投影零转换），API 层无需改动响应结构
2. **并发防护** — 原子写（tmp + os.replace）+ per-story 可重入线程锁（防并发 lost update）；实体 ID 分配另加进程级全局锁（ID 跨 story 全局唯一）
3. **锚点定位** — story 目录定位优先读 sessions 表 workspace_path 锚点，失效再 glob `*-{会话id前8}` 兜底

权威源切换历史：script_entities / episodes 两张历史表结构保留用于迁移对账，读写已切至 WorkspaceStore（见 `backend/core/persistence/script_manager.py` 模块注释）；存量数据迁移用 `backend/scripts/migrate_db_to_workspace.py`（--export/--verify/--cutover）。

## 关键流程

**story 树目录规范（workspace_store.py 模块 docstring）**

```
workspace/
└── {剧名}-{剧本会话id前8}/
    ├── MAP.md                          目录地图（自动渲染）
    ├── 00-ideation/story-logic.md      故事逻辑（构思收敛产物）
    ├── 01-outline/outline.md           全剧大纲（mindmap markdown，根标题即剧名）
    ├── 02-episodes/ep_NN-标题.md       分集设计
    ├── 03-entities/{chr|scn|clu|fs}_NNN-名字.md   全局实体卡
    └── 04-storyboards/ep_NN/
        └── vs-{视频会话id前8}/         同分集多次视频会话 = 兄弟 vs 目录
            ├── storyboard.md           分镜大纲导图
            └── seg_NN-标题.md          分镜（配置在 frontmatter）
```

数字前缀子目录常量（DIR_IDEATION…DIR_STORYBOARDS）保证目录树浏览时的阅读顺序。

**story 目录定位与生命周期**

1. `story_dir(sid)` — 取 `self._anchor_sm().get_session(sid)` 的 workspace_path 锚点拼 root 路径，is_dir 通过即返回；锚点失效记 warning 后回退 glob `*-{sid[:8]}` 目录名匹配；都没有返回 None
2. `ensure_story(sid, title)` — 定位不到则创建：per-story 锁内双检（防并发创建），目录名 `{sanitize_name(title or '未命名剧本', max_len=40)}-{sid前8}`，建 5 个子目录后回写锚点（`set_workspace_path`）并渲染 MAP
3. `rename_story(sid, new_title)` — 剧名确定/变更时正名；目标目录已存在则抛 WorkspaceStoreError；改名后同步锚点与 MAP
4. `write_outline` / `update_outline` — 落盘大纲时取 mindmap 根标题（`_mindmap_title` 解析首个 `# ` 行），目录名与剧名不一致即触发 rename_story 一次性正名；update_outline 强制 edited=True 且保留原 requirements
5. `story_title` / `story_cwd` — 前者为目录名去掉 -sid8 后缀的展示名；后者返回 story 根绝对路径（resolve），是 agent run_agent 的 cwd 来源（消费方：script_workflow.py、storyboard.py）
6. `delete_story(sid)` — shutil.rmtree 整棵树并清锚点（删除剧本会话时调用）

**通用文档读写原语**

1. `_read_doc` — frontmatter.load 读元数据与正文；`_norm_yaml` 把 YAML 解析出的 datetime 归一为 isoformat 字符串（与 DB row 的 str 类型对齐），递归处理 dict/list
2. `_static_write` — frontmatter.dumps 序列化后写 `{name}.tmp` 再 `os.replace` 原子落盘
3. `_write_doc` — 建父目录 + _static_write
4. `_replace_doc_file(dir, doc_id, name, meta, content)` — 写入 `{doc_id}-{净化名}.md` 并 glob 清掉同 id 旧命名文件（标题/名字变更后重命名）；`_doc_name` 用 `sanitize_name(name, max_len=30, fallback='untitled')` 净化标题，id 前缀保证排序与 glob 精确匹配
5. `_refresh(story)` — 每次写后惰性全量重渲染 MAP.md（文件量小，开销可忽略）

**正文小节渲染与转义（防 LLM 输出标题定界符冲突）**

1. 固定小节映射 — 分集 `EPISODE_SECTIONS`（梗概/矛盾链/因果链/结尾摘要/节点进展 → logline/conflict_chain/causality_chain/ending_summary/story_progress）；分镜 `SEGMENT_SECTIONS`（分镜大纲/分镜提示词 → outline/prompt，prompt 为空不渲染该节）
2. 转义 — 正文字段值中的行首 `## `（LLM 自由文本可能输出 markdown 标题）会与正文小节定界符冲突：写入时在行首标题前加一个 `\`（`_escape_headings`），读取时按已有反斜杠数量减一还原（`_unescape_headings`），双射往返（原文 `\## x` ↔ 文件 `\\## x`）
3. 解析 — `_split_sections` 按 `## 标题` 行切分正文为 {标题: 文本}，`_episode_from_doc`/`_segment_from_doc` 小节取值后反转义还原字段，组回旧 row 形状 dict

**实体注册表（全局唯一 ID）**

1. ID 形态 — `{chr|scn|clu|fs}_{3位以上数字}`（人物/场景/线索/伏笔前缀映射 ENTITY_ID_PREFIXES，中文标签 ENTITY_TYPE_LABELS）
2. `next_entity_id` — 仅预览用途；`_scan_next_entity_id` 在 `_ENTITY_ID_LOCK`（进程级，因 per-story 锁保护不到跨会话并发）内跨全工作区 glob `*/03-entities/{prefix}_*.md` 取 MAX+1，格式 `{prefix}_{n:03d}`
3. `upsert_entity` — 签名与旧 ScriptManager.upsert_entity 一致；entity_id 指定但文件不存在默认报错（agent 自纠），create_if_missing=True 允许按给定 ID 直接新建（DB→文件迁移路径）；新建时 ID 分配与落盘在同一 `_ENTITY_ID_LOCK + story 锁` 内原子完成（防跨会话并发撞号）；meta 缺省回落旧文件的 meta
4. 读写删均限定本 story（`_find_entity_file` 只在本会话实体目录内 glob——ID 全局唯一但写/删不得跨会话）；list_entities 排序与旧 DB 一致（entity_type ASC, entity_id ASC）
5. `set_entity_lookbook` — 只回写 lookbook_image_id/path 引用到 frontmatter（定妆照任务本体仍在 DB）

**分集设计与级联清理**

1. `upsert_episode` — 校验 `ep_NN` 形态后整文件覆写；meta 缺省回落旧值、edited 保留旧值、created_at 保留旧值
2. `update_episode_fields` — 人工编辑部分字段（allowed 集合：title/logline/conflict_chain/causality_chain/ending_summary/story_progress/character_ids/scene_ids/clue_refs/foreshadow_refs），title 变更联动文件名（复用 _replace_doc_file），edited=True
3. `delete_story_content` — 大纲重生成的级联清理：清空 02-episodes 与 03-entities 全部 .md 返回计数；**04-storyboards 保留**（视频会话数据不因剧本侧操作被删，与旧行为一致）；定妆照/素材图任务表仍在 DB，由调用方另行清理
4. `delete_episode` — 按 episode_id glob 删文件

**分镜（视频工作流产物）**

1. `storyboard_dir` — 确定性拼出 `04-storyboards/{ep}/vs-{视频会话id前8}`（不存在则 ensure_story）
2. `write_storyboard` — 清空 vs 目录（shutil.rmtree）后整体重写：storyboard.md 存导图 + 逐个 seg 文件（对应旧级联重置语义）；segment_count 写入 frontmatter
3. `_write_segment_file` — frontmatter 配置：index/title/mode（默认 all_reference）/overlap（默认 1）/duration（默认 15）/edited/reference_images/updated_at；文件名 `seg_{index:02d}-{标题}.md`
4. `replace_storyboard` — 整体替换 mindmap 和/或 segments（人工编辑导图 reconcile 后调用）；segments 替换先清全部 seg_*.md 再重写（分镜可能增删/改名），不改 created_at
5. `update_segment_fields` — 单分镜部分更新（title/outline/mode/overlap/duration/prompt/reference_images），整文件重写并置 edited=True
6. `episode_path` / `segment_path` — 返回分集/分镜文件绝对路径供 agent prompt 注入（消费方：storyboard.py 分镜大纲必读分集设计、上一分镜衔接）
7. `read_storyboard` — 组回旧 step_results.storyboard_outline.result_data 形状（mindmap/edited/segments/segment_count），segments 按 index 排序

**MAP.md 渲染与 Agent 入口**

1. `refresh_map(story)` — 全量重渲染 MAP.md：标题取目录名去后缀；「目录结构」列出各子目录文件清单（实体按 人物/场景/线索/伏笔 分组）、「检索建议」（Read outline / Glob+Grep 实体 / Grep 伏笔 ID 命中各集 frontmatter foreshadow_refs 等）、「边界规则」（Agent 只能在本目录内 Read/Grep/Glob、产物由系统统一写入只具备读权限）
2. `agent_entry(sid)` — 返回 {available, story_root, map_path, map_summary}；map_summary 截取 MAP「## 检索建议」之前的目录结构一节（检索建议与边界规则由调用方附加，避免重复）；story 不存在返回 available=False

**ID 白名单校验（防 glob 元字符注入）**

- `_EPISODE_ID_RE = ^ep_[0-9]{2,}\Z`、`_ENTITY_ID_RE = ^(chr|scn|clu|fs)_[0-9]{3,}\Z`（re.ASCII + \Z 绝对锚定；`$` 会放行尾换行、`\d` 会放行全角数字）
- 动机：API 路径参数直接拼 glob/文件路径，如 episode_id="*" 会令 glob("*-*.md") 误匹配并触发 _replace_doc_file 清空分集
- `EPISODE_ID_PATTERN` / `ENTITY_ID_PATTERN` 为 API/schema 共享的 pattern 字符串（pydantic/FastAPI 是 rust regex 引擎，其 `$` 即绝对末尾、`[0-9]` 为 ASCII，与 Python re 语义一致；由 `backend/api/v1/script_sessions.py` 导入使用）

## 涉及代码

- `backend/core/persistence/workspace_store.py` — WorkspaceStore 全部读写；WorkspaceStoreError（继承 ValueError 以复用 API/MCP 层既有捕获）；EPISODE_ID_PATTERN/ENTITY_ID_PATTERN
- `backend/core/persistence/session_manager.py` — sessions 表 workspace_path 锚点列与 set_workspace_path/get_session
- `backend/core/persistence/script_manager.py` — 生图任务状态机两张表保留；实体/分集读写已切至 WorkspaceStore
- `backend/core/config.py` — WORKSPACE_DIR（项目根 workspace/，import 时即 mkdir）
- `backend/core/utils/image_store.py` — sanitize_name（目录/文件名净化）
- `backend/deps.py` — get_workspace_store()（注入 session_manager=get_script_session_manager() 的单例工厂）
- `backend/core/services/workspace_projection.py` — 文件 + DB 薄 envelope 投影回旧 step_results JSON 形状（script_step_results/script_title/video_step_results）
- `backend/api/v1/script_sessions.py` — 剧本会话 API（ensure_story/get_episode/list_episodes/upsert_entity/delete_story 等 + ID pattern 校验）
- `backend/api/v1/sessions.py` — 视频会话 API（WorkspaceStoreError 捕获、video_step_results 投影）
- `backend/core/agents/script_workflow.py` — agent_entry/story_cwd 消费方（大纲、分集设计）
- `backend/core/agents/storyboard.py` — agent_entry/episode_path/segment_path/story_cwd 消费方（分镜）
- `backend/scripts/migrate_db_to_workspace.py` — 存量迁移 --export/--verify/--cutover（幂等导出、逐键对账、切换清表）

## 相关功能

- 剧本工作流（构思/大纲/分集设计，见 features/script-workflow.md）
- 分镜工作流（分镜大纲/细分镜，见 features/storyboard-workflow.md）
- 实体管理（实体卡/定妆照引用，见 features/entity-management.md）
- Claude Agent SDK 封装逻辑（story_cwd 提供 run_agent 的 cwd、agent_entry 提供 prompt 注入，见 logics/agent-sdk-wrapper.md）

## 注意事项

- 返回 dict 键与旧 SQLite row 完全一致是硬约束：新增文件字段时必须同步进 `_entity_from_doc`/`_episode_from_doc`/`_segment_from_doc` 的投影，否则 API 响应缺键
- 实体 ID 全局唯一（跨 story 分配）但读写删限定本 story：跨会话传错 ID 会得到 None/报错而非命中他story 文件
- per-story 锁是 RLock（可重入）：公开方法会嵌套调用（write_outline → rename_story），换成普通 Lock 会自死锁
- `_ENTITY_ID_LOCK` 是进程级锁且只在新建路径上与 story 锁同持（锁序恒定 _ENTITY_ID_LOCK → story lock），跨会话并发新建实体不会撞号
- 04-storyboards 在 delete_story_content（大纲重生成）中刻意保留；删除剧本会话走 delete_story 才整树删除
- 定妆照/素材图任务本体在 DB（ScriptManager 两张任务表），实体文件只存 lookbook_image_id/path 引用——删实体文件不会清理任务记录
- 正文小节转义为双射往返，但只处理 `## ` 及以上行首标题；若 LLM 输出其他定界符形态（如正文里伪造 `## 梗概`）会被误切分——字段值渲染前已统一转义，风险仅在人工直接编辑文件破坏结构时出现
- 锚点失效（目录被外部改名/移动）自动回退 glob 兜底，但目录名必须保留 `-{sid前8}` 后缀否则兜底也找不到
- 原子写仅覆盖单文件：多文件操作（write_storyboard 整体重写）在 story 锁内串行执行，非事务性——中途崩溃可能留下半成品 vs 目录，重生成幂等覆盖
- migrate 脚本仅在 cutover 前可用；cutover 后 DB 内容行已清、文件为唯一权威源；--verify 不对比时间戳（时间戳不保真）
- next_entity_id 仅预览用途（glob MAX+1 非原子），并发安全的新建必须走 upsert_entity 的空 ID 路径

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析生成，覆盖目录树规范/定位与生命周期/读写原语/转义机制/实体注册表/分集/分镜/MAP 渲染/ID 校验 |
