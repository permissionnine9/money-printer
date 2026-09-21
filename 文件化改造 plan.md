中间产物文件化改造实施计划（money-printer）

 Context

 系统两条工作流（创作剧本 / 视频生成）均由 Claude Agent SDK 驱动，但中间产物全存
 SQLite（data/sessions.db 的 step_results JSON 列 + episodes/script_entities 等表）。Agent
 运行时只能吃 Python 预拼的 prompt 上下文（wrapper.py 中 tools=[] 零工具、无 cwd），导致：
 1. 上下文过大 → 性能差，大剧本撑爆上下文窗口（storyboard.py:659 把全剧大纲全文 +
 本集上下文全文硬塞进 user_prompt）
 2. 上下文不足 → Agent"只见一斑"（如分镜管理第三步生成镜头脚本）
 3. Agent 的 Grep/Glob 自主检索能力被完全锁死

 改造方向（源自 文件化改造.md + 用户确认的三个决策）：
 - 文件为唯一权威源：中间产物全部 markdown 文件化（frontmatter 元数据承载关联信息），后端 API
 直接读写文件；SQLite 只留会话索引/模型配置/图片任务状态等非内容数据
 - Agent 只放开读：Read/Grep/Glob + cwd
 锁定剧本目录内自由探索；产物仍结构化输出，由后端解析后按规范落盘
 - 写迁移脚本：一键导出存量 DB 数据为新规范文件

 已验证可行性：SDK ClaudeAgentOptions.cwd（types.py:2086）与
 tools（:1965）可直接传；AgentRunOptions 已有 tools 字段（wrapper.py:48）。

 一、目录树规范

 根目录：项目根 workspace/（与 static/ 平级；.gitignore 加 workspace/）。

 剧本会话 = 一棵 story 树；视频会话不建树，分镜挂在 story 树下。同一分集多次创建视频会话 =
 兄弟 vs-* 目录；同会话重生成 = 原地覆写（与现 DB upsert 语义一致）。

 workspace/
 └── 林小雨的雨夜-1a2b3c4d/            ← {sanitize_name(title)}-{sid8}
     ├── MAP.md                        ← 目录地图 + Agent 检索建议 + 边界声明（store
 自动渲染）
     ├── 00-ideation/story-logic.md
     ├── 01-outline/outline.md         ← mindmap markdown，frontmatter:
 title/edited/requirements
     ├── 02-episodes/ep_01-巷口初遇.md
     ├── 03-entities/chr_001-林小雨.md / scn_001-… / clu_… / fs_…
     └── 04-storyboards/ep_01/
         ├── vs-9f8e7d6c/              ← {vs}-{视频会话id前8}
         │   ├── storyboard.md         ← mindmap + frontmatter(segment_count/edited)
         │   ├── seg_01-雨夜巷口全景.md
         │   └── seg_02-….
         └── vs-4a5b6c7d/…

 frontmatter 关键设计（关联信息全走元数据，正文为 markdown 内容）：
 - episode：characters: [chr_001]、scenes、clues/foreshadows: [{entity_id,
 action}]、edited、时间戳；正文固定小节 ## 梗概/矛盾链/因果链/结尾摘要/节点进展
 - entity：entity_type/name/meta（性格/欲望/伤口等）/lookbook_image_id/lookbook_image_path（
 核心素材任务本体留 DB，文件存引用）
 - segment：index/title/mode/overlap/duration/edited/reference_images[{image_id,image_path,de
 scription}]；正文 ## 分镜大纲 + ## 分镜提示词
 - 命名：ep_NN-标题.md、{prefix}_NNN-名字.md、seg_NN-标题.md；第 1 步以 未命名剧本-{sid8}
 建目录，第 2 步大纲落盘时一次性 rename 并同步 DB 锚点（sessions 新增 workspace_path 列）

 MAP.md 三段式：① 目录结构清单（每目录一行说明）② 检索建议（如 "Grep fs_001
 追伏笔跨集动作"）③ 边界规则（只能在本目录内 Read/Grep/Glob，禁止越界、禁止写）。

 二、存储层：backend/core/persistence/workspace_store.py（新建）

 - frontmatter 解析用 python-frontmatter + PyYAML（P0 加依赖）
 - WorkspaceStore 核心方法（返回 dict 键与旧 DB row 完全一致——前端零改动的关键，如
 frontmatter characters 读出映射回 character_ids）：
   - 生命周期：ensure_story / rename_story / story_path / delete_story / refresh_map /
 render_map
   - 内容：write_story_logic / write_outline / upsert_episode / update_episode_fields /
 list_episodes / upsert_entity / next_entity_id（glob 全工作区保全局唯一）/
 set_entity_lookbook / delete_story_content（大纲重生成级联清 02/03）
   - 分镜：storyboard_dir(vsid, ep)（路径确定性拼出，免查找表）/ write_storyboard（先清 vs
 目录再批量写，对应级联重置）/ update_storyboard_mindmap（平移 storyboard.py:203-277
 update_outline() 的标题匹配 reconcile 逻辑）/ update_segment（单文件重写，替代整条 JSON
 重写）/ set_segment_prompt
   - 通用 read_doc/write_doc：tmp + os.replace 原子写；per-story threading.Lock（继承现有
 _seg_locks 语义）；写后惰性 refresh_map
 - ScriptManager 实体/分集方法在 P3 停用、P6 删除；lookbook_*/episode_material_* 任务表留
 DB；SessionManager 加 sessions.workspace_path 列

 三、step_results 瘦身（行保留、内容变薄）

 - 行全保留（is_step_completed/clear_steps_after/can_execute_step
 完成态三件套免改），内容步骤 result_data 换薄 envelope：{"_success": true, "_artifact":
 "workspace", "path": "workspace/.../outline.md"}
 - 明确留 DB：story_ideation 的 agent_session_id（SDK resume 句柄）与 messages（UI 回放，md
 往返有损）；select_episode（小配置）；generate_videos（ComfyUI 任务状态机）
 - edited 标志 → 文件 frontmatter；_cancelled 仍走 DB envelope
 - 新建 backend/core/services/workspace_projection.py：script_step_results /
 video_step_results / segment_prompt_context，把文件+DB 投影回旧 JSON 形状（API 兼容层）

 四、Agent 调用改造

 - wrapper.py：加 READ_ONLY_TOOLS = ["Read", "Grep", "Glob"] 常量；AgentRunOptions 加 cwd
 字段，构造 ClaudeAgentOptions(cwd=...) 透传；run_conversation() 加 cwd 形参
 - 分镜提示词生成（核心痛点，storyboard.py:659-681）：cwd=story 根 + 只读工具，max_turns
 4→12；user_prompt 删「全剧大纲全文」「本集上下文全文」两段，改为「工作区路径 + MAP.md 摘要 +
 本集 episode 文件绝对路径 + 当前/上一分镜文件路径 + 必读清单 + 鼓励 grep 人物与伏笔」；保留
 skill 全文/overlap 硬规则/参考图清单（image_path 拼绝对路径供 Read 看图）；输出纯文本 →
 set_segment_prompt 落盘
 - 分镜大纲：删 get_story_outline MCP 工具（storyboard.py:105-117）；cwd+tools，max_turns
 5→12；storyboard_outline.md 模板 {{script_context}} 全文段换路径段
 - 素材图需求理解（generate_segment_material :447）：同上加 cwd+tools；JSON
 输出与生图链路不变
 - 分集设计（script_workflow.py:381）：upsert_*/save_episode MCP 保留但内部改写
 store（校验逻辑原样）；get_context 废弃 → prompt 改「先 Read MAP.md 与 outline.md」
 - 构思/大纲/核心素材生成：不变（对话型/单文件内联/结构化勾选型）
 - ScriptContextService 保留但数据源换 store，仅供 prompt-context 预览 API 与素材弹窗，不再进
 Agent prompt；删除全部截断常量（OUTLINE_MAX_CHARS=3500 等）

 五、API 改造（形状兼容，前端零改动为目标）

 ┌─────────────────────────┬───────────────────────────────┬─────────────────────────────┐
 │          端点           │           新数据源            │          兼容要点           │
 ├─────────────────────────┼───────────────────────────────┼─────────────────────────────┤
 │ GET script-session /    │ projection                    │ step_results 各键形状不变   │
 │ session 详情            │                               │                             │
 ├─────────────────────────┼───────────────────────────────┼─────────────────────────────┤
 │ GET/PUT outline、episod │ store                         │ dict 全键含                 │
 │ es、entities CRUD       │                               │ meta/lookbook_*/时间戳      │
 ├─────────────────────────┼───────────────────────────────┼─────────────────────────────┤
 │ ideation、lookbook 全部 │ DB（story_logic 落文件）      │ GET = DB messages + 文件    │
 │                         │                               │ story_logic 合并            │
 ├─────────────────────────┼───────────────────────────────┼─────────────────────────────┤
 │ PUT storyboard-outline  │ store.update_storyboard_mindm │ reconcile 后返回 {mindmap,  │
 │                         │ ap                            │ segment_count}              │
 ├─────────────────────────┼───────────────────────────────┼─────────────────────────────┤
 │ PUT segments config /   │                               │ 单文件写+store 锁；陈旧提示 │
 │ reference-images        │ store.update_segment          │ 词清空/完成态回退留         │
 │                         │                               │ workflow 层                 │
 ├─────────────────────────┼───────────────────────────────┼─────────────────────────────┤
 │ GET prompt-context      │ projection.segment_prompt_con │ SegmentPromptContext        │
 │                         │ text                          │ 形状不变                    │
 └─────────────────────────┴───────────────────────────────┴─────────────────────────────┘

 以 frontend/src/types/index.ts 每个 interface 为字段验收
 checklist；workflow_v2._get_video_segments（:114）改读 store。

 六、迁移脚本：backend/scripts/migrate_db_to_workspace.py（新建）

 三段式：
 - --export：只写文件、幂等。story → story-logic → outline → 实体 → 分集 → 回填
 workspace_path；视频会话 → vs 目录（storyboard + seg 文件）
 - --verify：DB↔文件逐键对账，不一致非零退出
 - --cutover：先备份 sessions.db.bak-<ts>，step_results 换薄 envelope；--purge-tables
 可选清数据但永不 DROP 表

 七、分阶段实施（每阶段独立验证）

 阶段: P0 依赖与配置
 内容: pyproject 加 python-frontmatter/PyYAML；.gitignore 加 workspace/；core/config.py 加
   WORKSPACE_DIR
 验证: uv sync 成功；import frontmatter 通过
 ────────────────────────────────────────
 阶段: P1 存储层
 内容: workspace_store.py 全量实现
 验证: 手工 smoke：全生命周期读写/rename/级联删/并发写/MAP 渲染；写 tests/ 单测
 ────────────────────────────────────────
 阶段: P2 迁移脚本
 内容: migrate_db_to_workspace.py 的 --export/--verify
 验证: 对真实 data/sessions.db 跑 export → verify 零 diff，人工抽查文件内容
 ────────────────────────────────────────
 阶段: P3 剧本侧切换
 内容: script_workflow.py 写路径改 store；MCP 工具内部改写 store；projection 层；sessions 加
   workspace_path 列
 验证: 先重跑 --export 消除窗口期分叉；用 /ego-browser 回归剧本 4 步；旧会话展示与改造前一致
 ────────────────────────────────────────
 阶段: P4 视频侧切换
 内容: storyboard.py 全部读写改 store；workflow_v2._get_video_segments
 验证: /ego-browser 回归视频 4 步：导图编辑 reconcile / 提示词 / 素材图 /
 视频重生成与备份恢复
 ────────────────────────────────────────
 阶段: P5 Agent 改造
 内容: wrapper cwd+tools；4 个生成入口 prompt 重写；删读侧 MCP
 验证: SSE 流出现 tool_use（Read/Grep）事件；提示词质量人工对比；--verify 仍零 diff
 ────────────────────────────────────────
 阶段: P6 收尾 cutover
 内容: --cutover 瘨身 DB；删除 ScriptManager 废弃方法
 验证: 全功能回归；DB 备份回滚演练

 八、风险与回滚

 1. 窗口期分叉（P2~P3 间 DB 仍被写）：P3/P4 上线流程固定「先重跑 --export 再切读」
 2. 级联回退：大纲重生成 → delete_story_content 清 02/03；分镜重生成 → write_storyboard 先清
 vs 目录；完成态逻辑仍在 DB 不动
 3. 并发：per-story 锁 + 原子 replace；单文件读-改-写比整条 JSON lost-update 面更小
 4. Agent 越界：SDK 无路径沙箱，靠 MAP 边界声明 + 只读白名单 + prompt
 约束（本机单用户可接受）；后续可加 PreToolUse hook 拒绝 cwd 外 Read
 5. 回滚：P3-P5 期间 DB 内容未删 → git revert 即回 DB 模式；P6 后靠 sessions.db.bak-* 还原

 关键文件清单

 新建：backend/core/persistence/workspace_store.py、backend/core/services/workspace_projectio
 n.py、backend/scripts/migrate_db_to_workspace.py
 重点修改：backend/core/agent_sdk/wrapper.py（cwd 透传）、backend/core/agents/storyboard.py（
 分镜读写+prompt）、backend/core/agents/script_workflow.py（MCP 落
 store）、backend/core/agents/workflow_v2.py（segments
 读取）、backend/core/services/script_context_service.py（数据源换
 store）、backend/api/v1/script_sessions.py、backend/api/v1/steps.py、backend/core/persistenc
 e/session_manager.py（workspace_path 列）、backend/core/persistence/script_manager.py（P6
 瘦身）、backend/prompts/storyboard_outline.md、backend/prompts/material_generate.md、.gitign
 ore、pyproject.toml
 复用：storyboard.py:203-277 update_outline() 的 mindmap↔segments reconcile、image_store.py
 sanitize_name、path_utils.py
 PROJECT_ROOT/resolve_project_path、json_utils.py、json_parser.py

 验证方式（端到端）

 1. 单测：P1 存储层 smoke + 现有 tests/ 回归
 2. 迁移对账：--export → --verify 零 diff
 3. 前端回归（按项目 CLAUDE.md 用 /ego-browser skill）：剧本 4 步 + 视频 4
 步全流程，重点第三步分镜管理（配置编辑/素材图/提示词生成）
 4. Agent 行为验证：SSE 事件流中观察 tool_use 事件（Read/Grep/Glob
 出现、路径均在剧本目录内）、生成产物落盘符合目录规范
 5. 兼容性：改造前后 API 响应 JSON 对比（frontend/src/types/index.ts 为验收清单）

 约束（项目 CLAUDE.md）

 - 不自行 git 提交/暂存/操作 git 记录
 - 前端交互验证必须用 /ego-browser skill