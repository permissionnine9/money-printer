---
name: 前端剧本工作台
摘要: 剧本 4 步向导页（构思→大纲→分集→定妆照），keep-alive 非卸载保 SSE/轮询，URL session_id 恢复会话。
tags: frontend, script-workflow, sse, polling, zustand
---

# 前端剧本工作台

**状态:** 已完成
**最后更新:** 2026-09-19

## 功能概述

剧本创作的主工作页面（路由 `/script`），以 antd Steps 4 步向导组织：故事构思（多轮 AI 聊天收敛故事逻辑）→ 故事大纲（markmap 思维导图生成/编辑）→ 分集设计（时间线 + 实体库 Tabs + 剧本导出）→ 剧本定妆照（按实体卡片生成/轮询）。核心设计是 **keep-alive 非卸载**：切换步骤仅 `display:none` 隐藏，SSE 观流与轮询进度不中断。

## 核心代码路径

- `frontend/src/pages/ScriptWorkflowPage.tsx` — 页面骨架：4 步 Steps 导航、HIDDEN 样式常量（display:none keep-alive）、URL session_id 读写
- `frontend/src/components/script/StepIdeationChat.tsx` — 第 1 步故事构思：`fetchSSE`（`frontend/src/api/sse.ts`）直跑形态聊天，边收 AgentEvent 边渲染
- `frontend/src/components/script/StepOutline.tsx` — 第 2 步故事大纲：参数化生成（POST /outline/generate 拿 run_id）+ markmap 预览 + 人工编辑
- `frontend/src/components/script/StepEpisodeDesign.tsx` — 第 3 步分集设计：`usePolling` 轮询 `loadEpisodes`+`loadEntities`、实体库 Tabs、完整剧本 markdown 下载
- `frontend/src/components/script/StepLookbook.tsx` — 第 4 步定妆照：`usePolling` 轮询 `loadEntities`/`loadImages` 状态机（pending/processing/completed）
- `frontend/src/components/script/AgentRunProgress.tsx` — 通用 agent 运行观流组件（run_id 形态 SSE，重连+seq 续传）
- `frontend/src/stores/scriptSessionStore.ts` — zustand 会话状态（currentSession/loading/error/loadSession）
- `frontend/src/utils/scriptMarkdown.ts` — 完整剧本 markdown 拼装 + Blob 下载

## 关键逻辑说明

1. **keep-alive**：4 个步骤组件始终挂载，非当前步骤用 `HIDDEN: CSSProperties = { display: 'none' }` 隐藏（ScriptWorkflowPage.tsx:22,99-110）——切步骤不断开 SSE、不丢生成进度
2. **URL 恢复**：挂载时从 `?session_id=` 读会话并 `loadSession`；`currentSession.session_id` 变化时 `history.replaceState` 回写 URL（不产生历史记录）
3. **浏览步骤纯前端**：`viewStep` 本地 state，切会话时同步为 `Number(currentSession.current_step)`，步骤内完成后不自动跳转
4. **两种异步消费形态**：ideation/message、ideation/finalize 走 `fetchSSE` 直跑（组件内边收边渲染）；outline/episodes/lookbook 生成类接口 POST 立返 run_id 后由 `AgentRunProgress` 观流；无 run 机制的长任务（分集设计、定妆照）用 `usePolling` 2s 轮询
5. 无会话时显示引导文案，会话的新建/切换/删除由左侧 `SessionSider`（MainLayout）承担

## 依赖与复用关系

- 依赖: `frontend/src/api/client.ts`（scriptSessionApi/scriptStepApi/entityApi）、`frontend/src/api/sse.ts`（fetchSSE 手写 SSE 解析）、`frontend/src/hooks/usePolling.ts`、`frontend/src/components/common/MindmapView.tsx`
- 被依赖: `frontend/src/App.tsx`（/script 路由挂载）
- 可复用组件: AgentRunProgress（视频工作台共用）、MindmapView、PromptViewerModal

## 注意事项

- keep-alive 意味着组件副作用（SSE/轮询）生命周期与会话绑定而非与步骤绑定，修改步骤组件时需注意卸载语义（实际不卸载）
- `markdown-it` 被 StepEpisodeDesign.tsx 直接 import 但未声明在 package.json dependencies（靠 markmap-lib 传递依赖），存在依赖漂移风险
- 定妆照轮询同时刷新实体列表（lookbook 引用回写实体 frontmatter 后需同步展示）

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
