---
name: 提示词管理
摘要: 以 markdown 文件（backend/prompts/）为中心的 LLM 提示词模板管理：网页编辑覆盖保存（无版本）、{{变量}} 渲染供剧本/视频工作流调用，配合 Agent 运行时 prompt 事件与 PromptViewerModal 实现最终提示词透明可查。
tags: 提示词模板, 后端API, 前端页面, Agent SDK, 文件存储
---

# 提示词管理

**状态:** 已完成
**最后更新:** 2026-09-19

## 功能概述

把剧本/视频工作流各步骤的 LLM 提示词从代码中抽出到 markdown 文件（`backend/prompts/` 目录，每个 .md 文件一个模板），提供网页端查看与编辑，保存即覆盖生效（无版本管理）。模板用 HTML 注释携带元数据（description/category/step），占位符用双花括号语法 `{{variable}}`，运行时由 `PromptManager.render` 做正则替换（不用 str.format，避免与提示词正文中的 JSON 花括号冲突）。

两条主线：

1. **模板管理**：前端 `/prompts` 页面（`PromptsPage`）→ `promptApi`（axios，`/api/v1`）→ `backend/api/v1/prompts.py` → `PromptManager`（读写 `backend/prompts/` 目录下的 .md 文件）。页面标题为「分片镜头 Skill 提示词管理」。
2. **运行时提示词透明化**：`backend/core/agent_sdk/wrapper.py` 在发起每次 Agent 调用前流出 `type="prompt"` 事件（最终渲染后的 system/user prompt 与模型名），前端 `AgentRunProgress` / `StepIdeationChat` 收到后显示「查看提示词」入口，用通用组件 `PromptViewerModal`（system/user 分页签 + 复制）展示。

## 核心代码路径

- `backend/core/services/prompt_manager.py` — 服务层：`PromptManager` 模板读写/渲染/元数据提取/路径防穿越，模块级常量 `PROMPTS_DIR`（backend/prompts/）与 `DEFAULT_TEMPLATES`，`get_prompt_manager()` 模块级单例
- `backend/api/v1/prompts.py` — API 层：`/api/v1/prompts` 下 3 条路由（列表/读取/保存），挂载于 backend/main.py:82 `include_router(prompts.router, prefix="/api/v1/prompts", tags=["提示词管理"])`
- `frontend/src/pages/PromptsPage.tsx` — 前端页面：左侧按分类分组的可折叠模板列表 + 右侧 TextArea 编辑器，脏状态跟踪与覆盖保存
- `frontend/src/api/client.ts` — 前端 API client：`promptApi`（第 295 行起），list/get/save 三方法，axios baseURL `/api/v1`
- `frontend/src/types/index.ts` — TS 类型 `PromptTemplate`（第 247 行起）：name/description/category?/step?/updated_at?/length?/content?
- `frontend/src/components/common/PromptViewerModal.tsx` — 通用提示词查看弹窗（system/user 分页签、字符数、复制），经 `frontend/src/components/common/index.ts` 导出
- `backend/core/agents/workflow_base.py` — 消费入口：`StepWorkflowBase.__init__`（第 27 行）`self.prompts = get_prompt_manager()`，ScriptWorkflow / StoryboardWorkflow 共用
- `backend/core/agent_sdk/wrapper.py` — prompt 事件源：`run_agent` 发起调用前 `emit(AgentEvent(type="prompt", system_prompt=..., user_prompt=..., model=env.get("ANTHROPIC_MODEL","")))`（第 129-132 行），`run_conversation` 内部走 `run_agent` 同样覆盖
- `backend/core/agent_sdk/events.py` — `AgentEvent` 数据类含 system_prompt/user_prompt/model 字段（第 30-31 行），`to_dict` 过滤空字段后经 SSE 下发

## 关键逻辑说明

### 模板文件与元数据（backend/prompts/，git 跟踪）

现有 7 个模板，首行 HTML 注释三件套 `<!-- description: -->` / `<!-- category: -->` / `<!-- step: -->`：

| 文件 | category | step | 渲染调用方（渲染为） |
|------|----------|------|---------------------|
| script_ideation.md | script | 1 | script_workflow.py:103/144 构思对话（system prompt） |
| script_ideation_finalize.md | script | 2 | script_workflow.py:145 收敛故事逻辑（user 消息） |
| script_outline.md | script | 3 | script_workflow.py:209 大纲生成（user prompt） |
| episode_design.md | script | 4 | script_workflow.py:533 分集设计（system prompt） |
| lookbook_prompts.md | script | 5 | script_workflow.py:637 定妆照 prompt（user prompt） |
| storyboard_outline.md | video | 1 | storyboard.py:154 分镜大纲（user prompt） |
| material_generate.md | video | 3.2 | storyboard.py:507 素材图生成（user prompt） |

注意混合用法：script_outline / lookbook_prompts / storyboard_outline / material_generate 模板渲染后作为 user prompt，配 `backend/core/agents/system_prompts.py` 中**硬编码**的 system prompt 常量（SCRIPT_OUTLINE_SYSTEM / LOOKBOOK_PROMPTS_SYSTEM / STORYBOARD_OUTLINE_SYSTEM / MATERIAL_GENERATE_SYSTEM / SEGMENT_PROMPT_SYSTEM）；script_ideation / episode_design 模板本身渲染为 system prompt，user 侧任务文本在代码内拼装。

### 服务层（backend/core/services/prompt_manager.py）

- `PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"` → `backend/prompts/`；`__init__` 先 `mkdir(parents=True, exist_ok=True)` 再 `_ensure_default_templates`。
- `list_prompts()`：按文件名升序遍历目录内全部 .md 文件，逐文件返回 name（去 .md 的 stem）、description、category、step、updated_at（st_mtime）、length。
- `load_prompt(name)`：文件不存在返回 None；`save_prompt(name, content)` 覆盖写并记日志。
- `render(name, variables)`：模板不存在抛 `FileNotFoundError`；`_PLACEHOLDER_PATTERN = \{\{\s*(\w+)\s*\}\}` 正则替换，未提供的变量替换为**空字符串**（静默，不报错），value 为 None 也转空串。
- 元数据提取：`extract_description/category`（正则 MULTILINE 匹配 HTML 注释，缺省空串）、`extract_step`（匹配 `(\d+(?:\.\d+)?)` 转 float，缺省 None）。
- `_safe_path(name)`：`re.fullmatch(r"[\w-]+", name)` 不通过抛 `ValueError("非法的提示词名称: ...")`（防路径穿越），通过则拼 `prompts_dir/{name}.md`。
- `DEFAULT_TEMPLATES` 内置默认模板**仅 2 个**：storyboard_outline、material_generate；`_ensure_default_templates` 只在文件不存在时写出。其余 5 个 script 系模板不在内置默认里，仅以 git 跟踪的文件存在。
- `get_prompt_manager()`：模块级单例（`_prompt_manager` 全局变量懒初始化）。

### API 层（backend/api/v1/prompts.py，挂载前缀 /api/v1/prompts）

| 路由 | 处理函数 | 行为 |
|------|---------|------|
| GET /prompts | list_prompts | 返回 `{success, prompts: [...]}`（manager.list_prompts 全量） |
| GET /prompts/{name} | get_prompt | 非法名称 ValueError → 400；文件不存在 → 404（`提示词模板不存在: {name}`）；返回 `{name, description, category, step, content}` |
| PUT /prompts/{name} | update_prompt | 请求体 `PromptUpdateRequest{content}`；先 load 判存在（无 → 404，**不能新建**）；ValueError → 400；成功返回 `{success, message:'提示词已保存', prompt:{name, description, category, step}}` |

无创建（POST）与删除（DELETE）路由——模板集合只能通过磁盘文件增删，网页端只能改内容。

### 前端页面（frontend/src/pages/PromptsPage.tsx，路由 /prompts）

- 路由注册 App.tsx:20 `<Route path="/prompts" element={<PromptsPage />} />`；侧边菜单 MainLayout.tsx:147「提示词管理」。
- 分类分组：`CATEGORY_ORDER = ['script','video','other']`（剧本创作/视频生成/其他），category 缺失或未识别归「其他」；组内按 step 升序，step 缺省排最后（`Infinity` 兜底）；分组可折叠（collapsed state）。
- `loadPrompts(selectName?)`：`promptApi.list` → 默认选中 step 最小的第一项（或指定项）；`selectPrompt` 调 `promptApi.get` 拉全文。
- 编辑：TextArea rows=24 等宽字体，任何输入置 dirty（顶部「未保存」Tag + 字符数统计）；`handleSave` 调 `promptApi.save`，成功 message 提示已保存到 backend/prompts/ 下对应 .md 文件并 `loadPrompts(selected.name)` 保持选中；保存按钮 `disabled={!selected || !dirty}`。
- 空态：无模板显示 Empty「暂无提示词模板」。

### 运行时提示词透明化（prompt 事件 → PromptViewerModal）

- 后端：`run_agent` 在 `client.query` 前流出 `AgentEvent(type="prompt", system_prompt=options.system_prompt or "", user_prompt=options.prompt, model=env.get("ANTHROPIC_MODEL",""))`；`AgentEvent.to_dict`（events.py）过滤空字段后走 SSE；多轮会话 `run_conversation` 内部委托 `run_agent`，同样覆盖。
- 前端消费两处：
  - `frontend/src/components/script/AgentRunProgress.tsx`：SSE `case 'prompt'` 存 state；运行卡片头部出现「查看提示词」按钮（EyeOutlined，prompt 存在才显示），点击开 `PromptViewerModal`。
  - `frontend/src/components/script/StepIdeationChat.tsx`：`ev.type === 'prompt'` 存 `lastPrompt`；对话区底部「查看本轮提示词」按钮 + 同弹窗。
- `PromptViewerModal`：Tabs 默认激活「用户提示词」页；systemPrompt 非空才追加「系统提示词」页；每页带字符数与「复制」按钮（navigator.clipboard，失败 message.error「复制失败」）；Modal 宽 860、footer=null、destroyOnHidden、标题带模型 Tag。

## 依赖与复用关系

- 依赖: FastAPI APIRouter（backend/api/v1/prompts.py）；pathlib 文件 IO（无数据库）；前端 antd（Card/Input/TextArea/Tabs/Modal/Tag/Empty/Spin）、axios（client.ts，baseURL /api/v1）；prompt 事件依赖 AgentEvent（backend/core/agent_sdk/events.py）与 run_agent（backend/core/agent_sdk/wrapper.py）
- 被依赖: backend/core/agents/workflow_base.py（StepWorkflowBase 持有 prompts 实例，ScriptWorkflow / StoryboardWorkflow 全部步骤渲染模板）、前端 AgentRunProgress / StepIdeationChat（PromptViewerModal）
- 可复用组件: `PromptViewerModal`（任何展示最终提示词的场景）；`PromptManager.render`（新增步骤只需在 backend/prompts/ 加文件 + 代码里 render）

## 注意事项

- **保存即覆盖、无版本管理**：无备份、无历史；保存后立即影响下一次生成调用（页面提示语亦如此声明）。
- **内置默认只覆盖 2 个模板且内容已滞后**：`DEFAULT_TEMPLATES` 仅 storyboard_outline / material_generate，且其内容落后于当前磁盘文件（如 material_generate 默认版仍是 `{{story_outline}}/{{episode_context}}` 上下文，磁盘版已改为 `{{workspace_section}}` 工作区检索式）。若磁盘文件被删，自动重建的是旧版默认内容而非线上最新版；5 个 script 系模板被删则完全不会重建（只能靠 git 恢复）。
- **API 不能增删模板**：PUT 对不存在的 name 返回 404；新增/删除模板需直接操作 backend/prompts/ 目录（7 个文件均被 git 跟踪）。
- **占位符静默替换**：render 时变量缺失替换为空串不报错——模板改出未知占位符或调用方漏传变量都不会失败，只会悄悄丢内容；模板不存在则抛 FileNotFoundError。
- **模板名约束**：`_safe_path` 要求名称匹配 `[\w-]+`，含 `/`、`.`、空格等抛 ValueError → API 400（防路径穿越）。注意 Python 的 `\w` 默认匹配 Unicode 字母数字，中文模板名可通过校验（实测 `中文模板` PASS）。
- **部分 system prompt 仍硬编码**：system_prompts.py 的 5 个 `*_SYSTEM` 常量不受本功能管理，网页上改不到。
- **相邻机制勿混淆**：`backend/core/services/video_prompt_skill.py` 的 video-prompt skill（backend/.claude/skills/video-prompt/ 的 SKILL.md + references 三篇）是因 Agent SDK 隔离模式（setting_sources=[]）无法原生加载项目级 skill，而同步到剧本工作区 `99-references/video-prompt/` 的**技能规范文件**（storyboard.py:695 generate_segment_prompt 使用），与 backend/prompts/ 模板渲染是两套机制；页面标题中的「Skill 提示词」指本页管理的模板，而非该 skill 目录。
- **updated_at 为文件 mtime**：列表返回 `st_mtime`（epoch 秒），前端当前未展示。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析生成（含 prompt 事件透明化与 PromptViewerModal） |
