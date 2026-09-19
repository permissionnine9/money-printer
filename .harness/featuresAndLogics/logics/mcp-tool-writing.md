---
name: 进程内 MCP 写侧工具逻辑
摘要: script_design MCP 五写工具，save_episode 强校验失败自纠重试
tags: MCP, AgentSDK, 分集设计, 强校验自纠
---

# 进程内 MCP 写侧工具逻辑

**最后更新:** 2026-09-19

## 逻辑概述

分集设计（episode_design）阶段由 `ScriptWorkflow.generate_episodes` 用 `claude_agent_sdk.create_sdk_mcp_server(name='script_design', version='1.0.0', tools=[upsert_character, upsert_scene, upsert_clue, upsert_foreshadow, save_episode])` 创建进程内 MCP server，把 5 个写侧工具注入 agent 运行环境。server 由 `ScriptWorkflow._build_design_mcp_server(session_id, single_episode_id=None)`（`backend/core/agents/script_workflow.py:395-483`）构建，经 `AgentRunOptions(mcp_servers={'script_design': mcp_server})` 注册到 run_agent；同一 run_agent 上读侧 `tools=READ_ONLY_TOOLS`（Read/Grep/Glob）、`cwd=self.store.story_cwd(session_id)`，形成"读侧检索文件 + 写侧走 MCP 工具"的混合工作区。

工具返回约定：成功 `_text_result({'ok': True, ...})` → `{'content':[{'type':'text','text':json.dumps(data, ensure_ascii=False)}]}`；失败 `_text_error(message)` → JSON `{'ok': False, 'error': message}`，**不抛异常**——错误以文本返回给 agent，由其自纠后重试。

设计意图是"轻/强校验分层 + 强校验自纠"：4 个 `upsert_*` 工具只透传 WorkspaceStore 抛出的 ValueError（轻校验），负责实体登记；`save_episode` 承担强校验（引用存在/集号连续/伏笔 payoff 晚于 plant/每集至少 1 人物 1 场景），校验失败返回错误与原因，agent 修正后重试。数据经 WorkspaceStore 落盘 workspace/ markdown（权威源），ScriptManager(scm) 仅管 DB 任务表。

## 关键流程

**全量分集生成主链路**

1. API 触发 — `backend/api/v1/script_sessions.py`（POST /{session_id}/episodes，script_sessions.py:273）→ `backend/deps.py` start_agent_run（AgentRunRegistry 后台任务 + SSE `/api/v1/agent-runs/{run_id}/events`）→ `ScriptWorkflow.generate_episodes`
2. 前置校验与清场 — 无 outline → ScriptWorkflowError(400)；先 `clear_steps_after('episode_design')` + `store.delete_story_content` + `scm.delete_script_data` 清空旧数据
3. 构建 MCP server — `_build_design_mcp_server(session_id, single_episode_id=None)`：`_upsert(entity_type)` 闭包工厂（script_workflow.py:398-426）用 `@sdk_tool(f'upsert_{entity_type}', ...)` 动态注册 4 个 upsert 工具，另有 `save_episode`
4. 运行 agent — `run_agent(AgentRunOptions(mcp_servers={'script_design': server}, tools=READ_ONLY_TOOLS, cwd=story_cwd))` → ClaudeSDKClient 子进程（bypassPermissions）；prompt 指示 agent 从 ep_01 到 ep_{count:02d} 逐集调 save_episode；`max_turns = clamp(EPISODE_TURNS_BASE=10 + EPISODE_TURNS_PER=3*episode_count, min=EPISODE_TURNS_MIN=20, max=EPISODE_TURNS_MAX=200)`
5. agent 调 upsert_* 登记实体 — handler 调 `self.store.upsert_entity(session_id, entity_type, name, description, meta, entity_id=args.get('entity_id') or None)`，entity_id 前缀 chr_/scn_/clu_/fs_、跨 story 全局分配；返回 `{'ok':True,'entity':entity}`；ValueError 捕获转 `_text_error`
6. agent 调 save_episode 保存分集 — handler 流程：
   1. 单集重设计限定：single_episode_id 非空且 episode_id 不等于它 → ScriptWorkflowError('本次为单集重设计，只允许保存 {id}')
   2. existing = store.list_episodes(session_id)；单集模式下把该集从 existing 中剔除（覆写语义）
   3. entities_by_id = {entity_id: entity}（store.list_entities）
   4. total_episodes = _count_outline_episodes(outline.mindmap)，大纲不存在则为 0
   5. `_validate_episode(episode, existing, entities_by_id, total_episodes)`
   6. 校验通过 → store.upsert_episode 落盘，返回 `{'ok':True,'episode':saved}`
   7. ScriptWorkflowError 捕获 → `_text_error` 返回给 agent 自纠
7. 收尾核对 — run 结束后 `len(store.list_episodes) != episode_count` → ScriptWorkflowError('分集不完整：大纲要求 N 集，实际保存 M 集，请重新生成')；成功才 `save_step_result('episode_design', {episode_count}, success=True)`

**单集重设计模式**（regenerate_episode_id 非空，POST /{session_id}/episodes/regenerate）：需分集已存在，否则抛 ScriptWorkflowError('分集不存在')（默认 status_code=400）；MCP server 传 single_episode_id 限定只可覆写该集；prompt 由 _build_single_episode_prompt 组装（工作区地图 + 前一集 ending_summary/causality_chain + 旧版设计与引用 + 下一集 logline/causality_chain + 已注册实体清单）；不推进步骤、不做集数核对。

**upsert 工具清单**（schema required: `["name"]`）

| entity_type | 工具名（含义） | entity_id 前缀 |
|---|---|---|
| character | upsert_character（人物，name 用姓名） | chr_ |
| scene | upsert_scene（场景） | scn_ |
| clue | upsert_clue（线索） | clu_ |
| foreshadow | upsert_foreshadow（伏笔） | fs_ |

upsert schema 字段：name（string，必填，人物用姓名）；description（string，视觉描述供生图，工具描述称 80 字内）；meta（object，任意附加信息——性格/欲望/地点/埋设意图等，伏笔的 open_ending 豁免标记即存于此）；entity_id（string，更新已有实体时传入，新增不传）。

**save_episode schema**

| 字段 | 必填 | 说明 |
|---|---|---|
| episode_id | 是 | 格式 `ep_NN`（正则 `^ep_(\d+)$`） |
| title | 是 | — |
| logline | 是 | 工具描述称 ≤60 字（描述文案，代码未强校验） |
| conflict_chain | 是 | ≤ CONFLICT_CHAIN_MAX=2000 |
| causality_chain | 是 | ≤ CAUSALITY_CHAIN_MAX=2000 |
| ending_summary | 是 | ENDING_SUMMARY_MIN=100 ≤ len ≤ ENDING_SUMMARY_MAX=300（强校验并回显当前字数） |
| character_ids | 是 | 至少 1 个，chr 前缀且存在 |
| scene_ids | 是 | 至少 1 个，scn 前缀且存在 |
| story_progress | 否 | 工具描述 200-500 字、≤600 字（代码强校验 ≤600，STORY_PROGRESS_MAX） |
| clue_refs | 否 | array of object `[{"entity_id":"clu_xxx","action":"plant/develop/reveal"}]` |
| foreshadow_refs | 否 | array of object `[{"entity_id":"fs_xxx","action":"plant/develop/payoff"}]` |

**集数统计** — `_count_outline_episodes(outline)`（模块级函数，script_workflow.py:766-774）：正则 `^#{2,3}\s*(?:第\s*(\d+)\s*集|EP\s*(\d+))` 多行/忽略大小写计数；无匹配则兜底所有 ## 标题数（max(...,1)）。

## 涉及代码

- `backend/core/agents/script_workflow.py` — `_build_design_mcp_server`（:395-483，create_sdk_mcp_server + 工具注册）、`_upsert` 闭包工厂（:398-426）、save_episode handler、`_validate_episode`（:266）、`_validate_episode_refs`（:319）、`update_episode_fields`（:381-393，人工编辑复用引用校验）、`generate_episodes`（:498）、`_count_outline_episodes`（:766-774）
- `backend/core/persistence/workspace_store.py` — WorkspaceStore：upsert_entity（:415）/ upsert_episode（:545）/ list_entities（:501）/ list_episodes（:641）/ story_cwd（:273）；实体 entity_id 前缀 chr_/scn_/clu_/fs_ 跨 story 全局分配；workspace/ markdown 为权威源
- `backend/core/agent_sdk/wrapper.py` — AgentRunOptions / run_agent：mcp_servers 注入 + 读侧 tools=READ_ONLY_TOOLS（wrapper.py:46）+ cwd=story_cwd → ClaudeSDKClient 子进程（bypassPermissions）
- `backend/api/v1/script_sessions.py`、`backend/deps.py` — start_agent_run（deps.py:90，经 AgentRunRegistry 后台运行）+ SSE 观流入口 `backend/api/v1/agent_runs.py`（GET /{run_id}/events）
- `backend/core/agents/system_prompts.py` — 其他 agent 的系统提示词常量；episode_design / script_ideation 等走 PromptManager 模板（`backend/prompts/*.md`），不在此文件
- `backend/core/config.py` — IMAGE_REQUEST_TIME_GAP=12（多张图连续提交间隔秒数，定妆照间隔提交用）

## 相关功能

- 分集生成 generate_episodes（全量 / 单集重设计，见关键流程）
- 工作区文件化持久化（WorkspaceStore，workspace/ markdown 权威源）
- Agent 运行与 SSE 事件流（AgentRunRegistry，另见 `sse-event-stream.md`）
- 定妆照 / Lookbook（LOOKBOOK_VIDEO_PARAMS：VideoParams(resolution='1080p', aspect_ratio='16:9') 为生图锚点；间隔 IMAGE_REQUEST_TIME_GAP=12 秒提交）

## 注意事项

**save_episode 校验规则**（_validate_episode / _validate_episode_refs）

| 规则 | 实现/报错 |
|---|---|
| episode_id 格式 | `_episode_number`：正则 `^ep_(\d+)$`，不匹配抛 'episode_id 格式非法（应为 ep_01）' |
| 集号连续 | existing 非空时 num 必须等于 len(existing)+1（'集号必须连续：当前应保存 ep_{n:02d}'）；existing 为空时 num 必须=1（'第一集必须从 ep_01 开始'） |
| 必填实体 | character_ids 至少 1 个、scene_ids 至少 1 个（'缺少出场人物/出场场景'） |
| 字数上限 | conflict_chain ≤2000；causality_chain ≤2000；story_progress ≤600 |
| ending_summary | 100 ≤ len ≤ 300，否则报错并回显当前字数 |
| 引用存在与类型 | character_ids 需以 chr 开头且存在于 entities_by_id；scene_ids 需 scn 前缀；clue_refs 需 clu 前缀；foreshadow_refs 需 fs 前缀；不存在或前缀不符 → '引用了不存在或类型错误的实体' |
| action 合法值 | refs 的 action 必须在 ('plant','develop','reveal','payoff') 白名单内（clue/foreshadow 共用同一白名单） |
| payoff 晚于 plant | `_validate_episode_refs` 合并 other_episodes+[当前集] 全局计算：plant_ep[eid]=最早 plant 集号、payoff_ep[eid]=最早 payoff 集号（min 聚合，缺省 999）；payoff 存在但从未 plant → '尚未 plant 就在 payoff'；plant_ep[eid] >= payoff_ep[eid] → 'payoff 集号必须晚于 plant 集号' |
| 线索 reveal 前置 | clue_refs 中 action=reveal 的实体：其更早集 plant/develop 的最小集号 clue_prior_ep[eid] 必须 < 当前集号 num，否则 'reveal 之前必须有更早集的 plant 或 develop'（同一集内先 plant 再 reveal 不算"更早"，clue_prior_ep >= num 即报错） |
| 末集伏笔回收 | total_episodes>0 且 num==total_episodes 时：sorted(set(plant_ep)-set(payoff_ep)) 中实体若其 meta 无 open_ending 标记 → '末集检查：以下伏笔已埋设但从未 payoff，请在本集补上 payoff（或在实体 meta 标记 open_ending=true 豁免）' |
| 校验失败处理 | save_episode 捕获 ScriptWorkflowError 返回 {ok:false,error} 文本（不抛异常），agent 据此修正后重试——即"强校验自纠"机制 |

**其他注意点**

- upsert 工具本身不做描述字数等强校验（"80 字内"仅是描述文案），仅透传 WorkspaceStore 的 ValueError（含 entity_type 非法、指定 entity_id 不存在等）
- logline ≤60 字、description 80 字内、story_progress 200-500 字均为工具描述文案；代码强校验仅覆盖 story_progress ≤600 与 ending_summary 100-300，其余未在代码中强制
- 人工编辑复用校验：`update_episode_fields(session_id, episode_id, fields)`（script_workflow.py:381-393）——fields 与 {character_ids, scene_ids, clue_refs, foreshadow_refs} 有交集时，合并当前集后调同一 `_validate_episode_refs(merged, others, entities_by_id)`；注意人工编辑只做引用校验，不做集号连续/字数/末集回收校验
- 后续几集的"增量可见"依赖 store.list_episodes 实时读文件（agent 写后几集前 Read 已保存分集小节），由 prompt 指示而非代码强制
- MCP 工具错误是否会触发 agent 重试取决于 agent 行为，代码侧仅保证错误以 {ok:false,error} 文本返回
- WorkspaceStore 落盘细节（已核实）：实体新建 ID 分配在模块级 `_ENTITY_ID_LOCK` + per-story 锁内原子完成，`_scan_next_entity_id` 跨全工作区（所有 story 目录）glob 扫描 MAX+1，与旧 DB 全局唯一语义一致；写文件走 `_replace_doc_file`（tmp + os.replace 原子写，frontmatter 元数据 + description 正文）；指定 entity_id 更新时限定本 story 查找，不存在抛 ValueError

**常量**（episode_design 相关）

| 常量 | 值 | 用途 |
|---|---|---|
| ENDING_SUMMARY_MIN / MAX | 100 / 300 | ending_summary 长度区间（强校验） |
| CONFLICT_CHAIN_MAX | 2000 | conflict_chain 上限 |
| CAUSALITY_CHAIN_MAX | 2000 | causality_chain 上限 |
| STORY_PROGRESS_MAX | 600 | story_progress 上限（强校验；工具描述另称 200-500 字） |
| EPISODE_TURNS_BASE / PER / MIN / MAX | 10 / 3 / 20 / 200 | max_turns = clamp(BASE + PER*episode_count, MIN, MAX) |
| LOOKBOOK_VIDEO_PARAMS | VideoParams(resolution='1080p', aspect_ratio='16:9') | 定妆照生图锚点 |
| IMAGE_REQUEST_TIME_GAP | 12（秒，backend/core/config.py） | 定妆照/多图连续提交间隔，防生图服务限流 |

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修正 — launch_agent_run 更正为 start_agent_run；单集重设计"分集不存在"报错更正为默认 400（非 404）；补齐 IMAGE_REQUEST_TIME_GAP=12；WorkspaceStore 落盘细节（全局 ID 锁/原子写）由"待补充"改为已核实描述 |
