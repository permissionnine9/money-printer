---
name: 前端剧本工作台
摘要: 剧本 4 步向导页（故事构思→大纲→分集→核心素材图），keep-alive 非卸载保 SSE/轮询，URL session_id 恢复会话；生成类任务经全局任务坞（agentRunStore+AgentRunDock）跨步骤跟踪，第 1 步 AI 输出即草稿可一键采纳，第 4 步支持从素材库导入核心素材图。
tags: frontend, script-workflow, sse, polling, zustand, 全局任务跟踪, 素材库
---

# 前端剧本工作台

**状态:** 已完成
**最后更新:** 2026-09-21

## 功能概述

剧本创作的主工作页面（路由 `/script`），以 antd Steps 4 步向导组织：故事构思（多轮 AI 聊天，**AI 输出即草稿、可一键采纳为故事逻辑**）→ 故事大纲（markmap 思维导图生成/编辑）→ 分集设计（时间线 + 实体库 Tabs + 剧本导出）→ 核心素材图（原「定妆照」，按实体卡片生成/轮询，支持从素材库导入复用）。核心设计是 **keep-alive 非卸载**：切换步骤仅 `display:none` 隐藏，SSE 观流与轮询进度不中断。

生成类任务（大纲/分集）已迁移至**全局任务跟踪**（agentRunStore + AgentRunDock + RunTaskBanner + useRunTask，见「前端公共设施」文档）：任务入队后跨菜单/跨步骤持续观流，完成自动刷新会话，不再依赖组件内本地观流。

## 核心代码路径

- `frontend/src/pages/ScriptWorkflowPage.tsx` — 页面骨架：4 步 Steps 导航、HIDDEN 样式常量（display:none keep-alive）、URL session_id 读写
- `frontend/src/components/script/StepIdeationChat.tsx` — 第 1 步故事构思：`fetchSSE`（`frontend/src/api/sse.ts`）直跑形态聊天，边收 AgentEvent 边渲染；AI 输出即草稿 + 采纳为故事逻辑
- `frontend/src/components/script/StepOutline.tsx` — 第 2 步故事大纲：参数化生成（POST /outline/generate 拿 run_id）+ markmap 预览 + 人工编辑；全局任务跟踪（kind='outline'）
- `frontend/src/components/script/StepEpisodeDesign.tsx` — 第 3 步分集设计：实体库 Tabs、完整剧本 markdown 下载；全局任务跟踪（kind='episodes'，含单集重设计）
- `frontend/src/components/script/StepLookbook.tsx` — 第 4 步核心素材图：`usePolling` 轮询 `loadEntities`/`loadImages` 状态机（pending/processing/completed）+ 素材库导入入口
- `frontend/src/components/script/LookbookLibraryModal.tsx` — 素材库选择弹窗（跨剧本复用已完成核心素材图，后端逻辑见 lookbook-library 文档）
- `frontend/src/components/script/AgentRunProgress.tsx` — 通用 agent 运行观流组件（run_id 形态 SSE，重连+seq 续传）
- `frontend/src/stores/scriptSessionStore.ts` — zustand 会话状态（currentSession/loading/error/loadSession）
- `frontend/src/utils/scriptMarkdown.ts` — 完整剧本 markdown 拼装 + Blob 下载

## 关键逻辑说明

1. **keep-alive**：4 个步骤组件始终挂载，非当前步骤用 `HIDDEN: CSSProperties = { display: 'none' }` 隐藏（ScriptWorkflowPage.tsx）——切步骤不断开 SSE、不丢生成进度
2. **URL 恢复**：挂载时从 `?session_id=` 读会话并 `loadSession`；`currentSession.session_id` 变化时 `history.replaceState` 回写 URL（不产生历史记录）
3. **浏览步骤纯前端**：`viewStep` 本地 state，切会话时同步为 `Number(currentSession.current_step)`，步骤内完成后不自动跳转
4. **两种异步消费形态**：ideation 聊天走 `fetchSSE` 直跑（组件内边收边渲染）；outline/episodes 生成类接口 POST 立返 run_id 后**入队全局任务跟踪**（agentRunStore.addRun + AgentRunDock 观流 + RunTaskBanner/useRunActive/guardRunStart 呈现状态）；核心素材图生成/轮询仍为 `usePolling` 2s 轮询
5. **无会话时显示引导文案**，会话的新建/切换/删除由左侧 `SessionSider`（MainLayout）承担
6. **StepIdeationChat 叙事交互（a427b3e 优化）**：
   - 交互模式从「聊完必须点 AI 收敛」改为「**AI 输出即草稿 + 用户可直接采纳**」；
   - AI 回复正文匹配 `/^核心情境[:：]/m`（looksLikeStoryLogic）时自动填入故事逻辑编辑框并提示；未命中则不自动填入（可手动编辑）；
   - 每条 AI 消息尾部提供「采纳为故事逻辑」按钮 → handleAdopt → `scriptStepApi.adoptStoryLogic`（不经 LLM 收敛直接完成第 1 步）；
   - 原「确认故事逻辑」按钮降级为「让 AI 收敛故事逻辑」；
   - 新增剧本名编辑：saveTitle → `scriptStepApi.setStoryTitle`（联动 loadSessions 刷新侧栏）；
   - PromptViewerModal「查看本轮提示词」（system/user prompt + model）；
   - Enter 发送 / Shift+Enter 换行；会话切换时草稿与标题回填，防止旧值覆盖新会话编辑框。
7. **StepOutline / StepEpisodeDesign 全局任务跟踪**：
   - 迁移到 agentRunStore + RunTaskBanner + useRunTask；kind 分别为 `'outline'` / `'episodes'`；
   - episodes 含单集重设计（episodeId 追踪）；`guardRunStart` 防重复入队（POST 在途或已有同类任务时 message.warning 拦截）；
   - `fetchSeq` ref 丢弃迟到旧响应；running→false 跳变后做最终拉取兜底，避免漏掉最后一次落库。
8. **StepLookbook 与素材库**：
   - 实体卡片「从素材库选择」按钮（已有图/未生成两处入口）打开 LookbookLibraryModal；
   - 导入成功 handleImported **同时刷新素材列表和实体列表**（实体 frontmatter 锚点已变）；
   - LookbookLibraryModal（约 125 行）：打开拉 `scriptStepApi.getLookbookLibrary` 分组 → 过滤目标实体当前已锚定的图、源实体已删的素材标注「实体已失效」→ 复用 MaterialGrid 分组展示 → 单选（再点取消）→「绑定到实体」`importLookbookImage` → onImported(image) 回调并关闭弹窗；
   - 素材库的后端查询/导入/级联保留逻辑见 lookbook-library 文档。
9. **类型与 API**：`frontend/src/types/index.ts` 新增 `LookbookLibraryItem`/`LookbookLibraryGroup`；`AgentEvent.type` 新增 `'queued'`/`'started'`（含 queue_position，对应后端 FIFO 运行队列、并发上限 MAX_CONCURRENT_RUNS=5）；client.ts 的 scriptStepApi 新增 setStoryTitle/adoptStoryLogic/getLookbookLibrary/importLookbookImage。

## 依赖与复用关系

- 依赖: `frontend/src/api/client.ts`（scriptSessionApi/scriptStepApi/entityApi）、`frontend/src/api/sse.ts`（fetchSSE 手写 SSE 解析）、`frontend/src/hooks/usePolling.ts`、`frontend/src/components/common/MindmapView.tsx`、全局任务跟踪设施（agentRunStore/useRunTask/RunTaskBanner/AgentRunDock，见「前端公共设施」文档）
- 被依赖: `frontend/src/App.tsx`（/script 路由挂载）
- 可复用组件: AgentRunProgress（视频工作台共用）、MindmapView、PromptViewerModal；LookbookLibraryModal 为剧本侧专用（依赖 MaterialGrid 分组展示）

## 注意事项

- keep-alive 意味着组件副作用（SSE/轮询）生命周期与会话绑定而非与步骤绑定，修改步骤组件时需注意卸载语义（实际不卸载）
- `markdown-it` 被 StepEpisodeDesign.tsx 直接 import 但未声明在 package.json dependencies（靠 markmap-lib 传递依赖），存在依赖漂移风险
- 核心素材图轮询需同时刷新实体列表（lookbook 引用回写实体 frontmatter 后需同步展示）；素材库导入成功后同样双刷（素材列表 + 实体列表，frontmatter 锚点已变）
- StepIdeationChat 的自动填草稿依赖 AI 回复包含「核心情境：」行（正则 `/^核心情境[:：]/m`），AI 未按格式输出时不触发自动填充，需手动编辑或让 AI 收敛
- 全局任务跟踪的任务卡片在 AgentRunDock（MainLayout 挂载）中保活观流，切换菜单/步骤不丢进度；guardRunStart 是防重复入队的唯一闸门

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-21 | StepIdeationChat 叙事优化（AI 输出即草稿/「采纳为故事逻辑」adoptStoryLogic/剧本名编辑 setStoryTitle/PromptViewerModal/Enter 与 Shift+Enter/草稿回填）；StepOutline、StepEpisodeDesign 迁移全局任务跟踪（kind='outline'/'episodes'，guardRunStart 防重复入队、fetchSeq 丢弃迟到响应、running→false 最终拉取兜底）；StepLookbook 新增「从素材库选择」入口与 LookbookLibraryModal（导入后双刷）；types 新增 LookbookLibraryItem/LookbookLibraryGroup、AgentEvent 新增 queued/started；术语「定妆照」更名为「核心素材图」 |