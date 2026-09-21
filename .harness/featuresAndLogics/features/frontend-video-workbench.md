---
name: 前端视频工作台（WorkflowPage 4 步向导）
摘要: 视频生成工作流的前端工作台：路由 / 的 WorkflowPage 以 keep-alive 方式组装 4 步组件（选集/分镜大纲/分镜管理/视频），sessionStore/workflowStore 双状态层，生成任务经全局任务坞（agentRunStore+RunTaskBanner）跟踪，ComfyUI 视频生成为后台任务 + 3 秒轮询（maxPolls 兜底），配套素材图选择/AI 生成/@ 引用输入三个 material 弹窗组件。
tags: 前端, 视频工作流, 页面组件, zustand, 轮询, SSE, 全局任务跟踪
---

# 前端视频工作台（WorkflowPage 4 步向导）

**状态:** 已完成
**最后更新:** 2026-09-21

## 功能概述

视频生成工作流的前端入口（App.tsx 路由 `/` → WorkflowPage）：以 4 步向导形态驱动后端视频会话（select_episode → storyboard_outline → segment_management → generate_videos）。页面把 4 个步骤组件全部常驻挂载、非当前步骤仅 `display:none` 隐藏（keep-alive），保证切步骤不断开 SSE 观流、不丢流式/生成进度。**Step6Videos.tsx 是第 4 步「视频」的遗留文件名**（历史 6 步时代命名；StepNavigator.tsx:10-15 的 STEPS 注释明确 4 步结构），步骤数与文件名勿混淆。

状态分两层：`sessionStore`（zustand）持有会话详情并负责后端步骤名 → 前端索引的转换；`workflowStore` 仅维护「用户当前浏览的步骤」，步骤执行由各步骤组件直接调 `stepApi` 完成后 `refreshSession()` 刷新。

异步交互两种模式：Agent 类任务（分镜大纲生成、分镜提示词生成）走 run_id + **全局任务跟踪**（agentRunStore + AgentRunDock + RunTaskBanner/useRunTask，跨菜单切换不丢）；视频生成为 ComfyUI 后台任务 + `usePolling` 3 秒轮询会话详情（maxPolls 次数上限兜底）。

后端链路与数据契约见「视频创作工作流」文档；AgentRunProgress/MindmapView/LazyVideo/usePolling/imageSrc 及全局任务跟踪设施见「前端公共设施」文档，本文不重复展开。

## 核心代码路径

- `frontend/src/pages/WorkflowPage.tsx` — 工作台页面：URL session_id 同步、current_step → workflowStore 同步、4 步组件 keep-alive 组装
- `frontend/src/components/workflow/StepNavigator.tsx` — 步骤导航（antd Steps，4 步标题与说明；:10-15 STEPS 注释明确 4 步）
- `frontend/src/components/workflow/StepSelectEpisode.tsx` — 步骤 1：选剧本会话 + 分集卡片 + 视频参数表单（含重新选集级联确认）
- `frontend/src/components/workflow/StepStoryboardOutline.tsx` — 步骤 2：分镜大纲生成（全局任务跟踪 kind='storyboard_outline'）、导图预览/编辑双模式、重新生成级联确认
- `frontend/src/components/workflow/StepSegmentManagement.tsx` — 步骤 3：左右分栏的分镜配置（分镜形式/overlap/参考素材图/提示词生成，confirming 防重复提交）
- `frontend/src/components/workflow/Step6Videos.tsx` — 步骤 4「视频」（**遗留文件名**，955 行）：分镜轨道 renderTrain + ComfyUI 导入/生成/取消/备份恢复 + 最终成片预览
- `frontend/src/components/workflow/material/MaterialPickerModal.tsx` — 素材图选择弹窗（定妆照/本集素材/本分镜素材 3 个 tab，多选/单选）
- `frontend/src/components/workflow/material/MaterialGenerateModal.tsx` — AI 生成素材图弹窗（提示词 + @ 引用/选图/上传参考图 ≤4 张 + 生图模型选择）
- `frontend/src/components/workflow/material/MentionImageInput.tsx` — `@` 图片引用输入框（触发词检测、候选下拉、mentions chips 为真相源）
- `frontend/src/components/workflow/index.ts` — workflow 组件统一导出（StepNavigator + 4 步组件）
- `frontend/src/stores/sessionStore.ts` — 会话状态：currentSession/sessions/loading/error 与 create/load/delete/refresh 动作，stepNameToIndex 转换
- `frontend/src/stores/workflowStore.ts` — 仅 currentStep/setCurrentStep（用户浏览步骤）
- `frontend/src/types/index.ts` — STEP_NAMES/STEP_NAME_TO_INDEX（4 步名 ↔ 索引）、Session/SessionDetail/StoryboardSegment/PoolMaterial/MaterialPoolGroup 等类型
- `frontend/src/api/client.ts` — stepApi 全部步骤端点（select-episode、storyboard-outline、storyboard-segments、material-pool、importComfyUI/startComfyUIVideo/cancelVideos/restoreVideosBackup 等）
- `frontend/src/utils/imageSrc.ts` — 图片路径 helper：http(s) 原样返回，本地相对路径补 `/` 前缀

## 关键逻辑说明

### 1. WorkflowPage — 页面骨架与 keep-alive

- 路由挂载：App.tsx `<Route path="/" element={<WorkflowPage />} />`，外层 MainLayout（仅 `/` 与 `/script` 显示会话侧栏）。
- URL 会话同步：挂载时 `getSessionIdFromUrl()` 读 `?session_id=` 调 `loadSession` 恢复；`currentSession.session_id` 变化经 `window.history.replaceState` 写回 URL，无会话时删除参数。
- current_step 同步策略：useEffect 仅依赖 `currentSession?.session_id`（会话切换时）把 `currentSession.current_step` 写入 `workflowStore.setCurrentStep`——生成完成推进的 current_step 不打断用户正在浏览的步骤（与剧本侧一致）。
- keep-alive：`const HIDDEN: CSSProperties = { display: 'none' }`，4 个步骤组件外层 div 按当前步骤切换 `undefined/HIDDEN` 样式，组件不卸载。
- 无会话且非 loading 时显示欢迎引导文案（「从左侧会话管理中新建一个视频会话即可开始创作」）。
- error 状态经 useEffect 弹 `message.error` 后 `clearError()`。

### 2. 状态层 — sessionStore / workflowStore

sessionStore（zustand）：

- `transformSessionData` 把后端原始会话（current_step 为步骤名字符串）转为前端 SessionDetail（current_step 为索引）。`stepNameToIndex`：STEP_NAME_TO_INDEX 直接映射；current_step 无效但已完成 `generate_videos` 时显示最后一步；否则回退 0。
- 动作：`createSession`（sessionApi.create 后拉详情）、`loadSession`、`loadSessions`（列表逐条转换索引）、`deleteSession`（删后重拉列表，删的是当前会话则置 currentSession=null）、`refreshSession`（按 currentSession.session_id 重拉详情，失败写 error）、`setCurrentSession`、`clearError`。

workflowStore：仅 `currentStep: number` + `setCurrentStep`。文件头注释明确「各步骤的执行由对应步骤组件直接调用 stepApi 完成并刷新会话，此处仅维护用户当前浏览的步骤」。

### 3. StepNavigator — 步骤导航

- 4 步常量（StepNavigator.tsx:10-15 STEPS 注释明确 4 步）：从剧本选集 / 分镜大纲 / 分镜管理 / 视频（与 types STEP_NAMES 对应）。
- antd `Steps` 的 `current` 取 `currentStep`（用户浏览步骤）而非 `session.current_step`（会话完成步骤），`onChange` 直接回调 `onStepChange`（即 setCurrentStep）——允许自由跳转浏览，完成态仅由各步骤组件内部按 completed_steps 渲染。

### 4. 步骤 1 — StepSelectEpisode

- 剧本会话加载：`scriptSessionApi.list()` 后过滤 `completed_steps` 含 `episode_design` 的会话（仅这些可选）；空态 Empty 提示「先到创作剧本完成分集设计」。
- 分集加载：选中剧本会话后 `scriptStepApi.listEpisodes(id)`，卡片网格（Row/Col xs24 sm12 md8）点击选择，选中卡片高亮 + 「已选」Tag。
- 视频参数 Form：resolution（720p/1080p/4K，默认 1080p）、aspect_ratio（16:9/4:3/1:1/9:16/21:9，默认 16:9）、max_segment_duration（InputNumber 5-30 秒，必填，默认 15）。
- 提交：`stepApi.selectEpisode(session_id, {script_session_id, episode_id, resolution, aspect_ratio, max_segment_duration: values.max_segment_duration || 15})` → 成功后 `refreshSession()`。
- 已完成视图：Descriptions 摘要（剧本会话前 8 位、分集 ID·标题、视频参数）+「重新选集」按钮。若有后续步骤已完成（SUBSEQUENT_STEPS = storyboard_outline/segment_management/generate_videos），先 Modal.confirm 列出将被清空的步骤再进入编辑；页面另有黄色警示条提示「重新选集将重置这些步骤」。
- 编辑模式预填当前 stepResult（script_session_id/episode_id/三参数），按钮文案变「确认重新选集」。

### 5. 步骤 2 — StepStoryboardOutline（全局任务跟踪）

- 数据：`step_results.storyboard_outline.result_data` 的 mindmap（markdown 导图）、segments（StoryboardSegment[]）、segment_count、edited 标记。
- 导图拼接 `buildMindmap(withDuration)`：逐行扫描 mindmap，`### ` 开头的行按序对应 segments[i]，把分镜内容（outline）压成单行 `- ` 列表子节点；withDuration=true（预览）时标题行追加 `Ns · overlap Ns` 后缀（overlap 仅 index>0 且 >0 时显示），编辑态不加后缀。预览用 `MindmapView`（height 520）渲染；**mindmap 变化时渲染期自动切回预览模式**。
- 生成：`stepApi.generateStoryboardOutline(session_id, extra_prompt?)` 返回 run_id → **入队全局任务跟踪**（agentRunStore.addRun，kind='storyboard_outline'）——原先组件内本地内嵌 AgentRunProgress 观流改为全局 agentRunStore + RunTaskBanner（useRunActive/useRunError/guardRunStart），任务进度呈现在右上角 AgentRunDock，**跨菜单切换不丢**；done 且 success 时 `refreshSession()` 并回到预览态。已有大纲时「重新生成」先弹补充要求 Modal（内含 9 条 PRESET_PROMPTS 快捷下拉，选中以「；」拼接到输入框后自身回位），确认后再 Modal.confirm 警告「将清空分镜配置、已生成的分镜提示词与视频数据」；无大纲（上次失败）则直接执行/重试。
- 编辑态：TextArea（rows=20，monospace）编辑 markdown，空内容拦截；保存调 `stepApi.updateStoryboardOutline(session_id, markdown)`（PUT），后端解析同步回 mindmap 与 segments。
- 卡片头：完成勾图标、`edited` 时「已人工修改」Tag、segment_count 时「N 个分镜」Tag；下游（segment_management/generate_videos）已完成时显示黄色警示「重新生成大纲将清空这些数据；仅保存编辑不会清空」。
- canExecute 门槛：completed_steps 含 `select_episode`，否则提示「请先完成第 1 步」。

### 6. 步骤 3 — StepSegmentManagement 与 material 组件

主组件（左右分栏，左 260px 分镜列表 + 右选中分镜详情）：

- 数据：storyboard_outline.result_data.segments；canExecute 需 `storyboard_outline` 完成；列表空提示回第 2 步重新生成。
- 分镜配置：MODE_OPTIONS 四种分镜形式（first_frame/last_frame/all_reference/first_last_frame），其中三个标注「暂未实现关联逻辑」，仅 `all_reference` 全能参考模式启用后续交互。切换调 `stepApi.updateSegmentConfig(session_id, index, {mode})`。
- overlap 滑块（仅全能参考模式）：Slider 0-3 步进 1，`value = selected.overlap ?? 1`，index=0（首个分镜）禁用并提示「首个分镜无上一分镜，不承接」；文案说明 0=不承接、1~3=承接上一分镜。
- 参考素材图（仅全能参考模式）：缩略图 + 描述 TextArea（descDrafts 草稿，onBlur 时与现值不同才提交）+ 更换单张/移除（Popconfirm，注明「仅解除关联，不删除素材库记录」）。保存统一走 `stepApi.updateSegmentReferenceImages(session_id, index, [{image_id, description}...])` 全量覆盖；追加时按 image_id 去重，更换单张时描述重置为库内默认。
- 分镜提示词生成（仅全能参考模式，按钮 disabled 否则）：先 `stepApi.getSegmentPromptContext(session_id, index)` 拉上下文（story_outline/episode_context/当前分镜/参考素材图/overlap 与衔接规则）在 Modal 内逐块预览；确认后 `stepApi.generateSegmentPrompt(session_id, index)` 返回 run_id → **addRun 入队全局任务跟踪（kind='segment_prompt'）**，进度提示语「进度见右上角后台任务」；**提交按钮加 confirming 防重复点击守卫**。已生成提示词可一键复制（navigator.clipboard）。
- 完成分镜：`stepApi.completeSegment(sessionId, index, completed)` **单分镜完成**（原 completeSegmentManagement 整步完成语义已改为按分镜粒度标记）；页面底部 Alert 提示「修改分镜配置会清空该分镜已生成的提示词并回退完成状态」。

MaterialPickerModal（素材图选择）：

- 打开时 `stepApi.getMaterialPool(session_id)` 拉分组；Tab1「定妆照」= key 为 lookbook 的组，Tab2「本集素材」= 其余组（含其他集素材），传入 segmentMaterials 时增加 Tab3「本分镜素材」。
- `multi=true` 多选（底部确认按钮，显示已选张数）；`multi=false` 单选点击即确认（「更换」场景）。excludeImageIds 过滤已引用素材。

MaterialGenerateModal（AI 生成素材图）：

- 自定义提示词（MentionImageInput，支持 `@` 引用素材池图片）+ 自定义参考图（素材库选择/上传，合计 ≤4 张，refCount ≥4 时按钮禁用）+ 生图模型下拉（`modelApi.list('image')`，默认不选）。
- 提交 `stepApi.generateSegmentMaterial(session_id, segmentIndex, {user_prompt, mentioned_image_ids, reference_paths, model_config_id?})` 返回 run_id → AgentRunProgress 观流（流程：AI 需求理解 → 生图 → 归档本集图库 → 自动加入本分镜）；成功后 onGenerated()（父组件 refreshSession）并关弹窗。生成中不允许关闭。
- 上下文摘要区展示自动注入的剧本大纲/本集脚本/当前分镜内容。

MentionImageInput（@ 引用输入）：

- onChange 时以正则 `(^|\s)@([^\s@]*)$` 检测光标前触发词，命中则弹候选下拉（按 title/description/image_id 过滤、排除已引用）；选中后把触发词替换为 `@名称 ` 并恢复光标（requestAnimationFrame）。
- mentions chips（closable Tag）为真相源，提交以该数组为准；文本中的 `@名称` 仅为装饰，不做反向解析。onBlur 延迟 150ms 关闭下拉以避免点选先失焦。

### 7. 步骤 4 — Step6Videos（955 行，重构后；遗留文件名）

- 文件名说明：Step6Videos.tsx 为历史 6 步时代命名，实际是第 4 步「视频」；StepNavigator.tsx:10-15 的 STEPS 注释明确 4 步结构。
- canExecute：completed_steps 含 `segment_management`；分镜预览数据：优先 legacy `generate_segment_scripts` 结果兜底，否则由 storyboard_outline.segments 映射（content = prompt || outline，duration = max_segment_duration || 15）。
- **分镜轨道 renderTrain**：分镜以叠层卡片轨道呈现——卡片间 -24px 负 margin 表现 overlap 视觉；checkbox 勾选分镜且约束**连续勾选（不可跳选）**；未配置（无提示词）的分镜显示虚线占位；`longestRun`/`splitContiguousRuns` 计算连续段，默认选中最长连续段。
- 生成链路三段：`handleImport`（`stepApi.importComfyUI`，可带 globalPrompt）→ `handleGenerate`（`stepApi.startComfyUIVideo` 启动生成）→ `handleCancel`（`stepApi.cancelVideos` 停止）。
- 备份恢复：`handleRestoreBackup` → `stepApi.restoreVideosBackup`；hasBackup 判定基于 `_backed_up_count` / `_old_video_path`，且非生成中可用。
- 分镜详情 Modal：查看单分镜的配置/提示词/生成结果。
- 最终成片预览：final_video/timeline_data——LazyVideo 播放 + Descriptions（分段数量/段间 overlap/参考图 timeline_data.images 数/参考音频 audios 数/任务 prompt_id 可复制）+ Collapse 展示 timeline_data JSON。
- 生成中判定 `isGenerating = hasPendingVideos || stepResult._generating === true || loading`；`usePolling(refreshSession, {interval: 3000, enabled: hasPendingVideos || isBackgroundGenerating})`，并以 **maxPolls 次数上限兜底**（防后端异常时无限轮询）。
- 分段视频卡：getVideoStatus 优先 task_status（completed/pending/failed/cancelled），无 task_status 时按 video_path 兼容判断（无路径→pending、「生成失败」前缀→failed、否则 completed）；pending 显示 Spin 占位、cancelled 显示已取消占位、failed 显示失败占位。
- 本地路径展示统一 `getMediaSrc`：http(s) 原样、相对路径补 `/` 前缀（与 utils/imageSrc.ts 同语义的组件内副本）。
- 重新生成链路（regenerateVideos/regenerateSingleVideo）已删除（client.ts 同步移除）。

## 依赖与复用关系

- 依赖: antd ^6.2.2（Steps/Card/Modal/Segmented/Slider/Tabs/Upload/Alert/Checkbox 等）、react-router-dom ^7（路由与 URL 操作）、zustand ^5（sessionStore/workflowStore/agentRunStore）、axios（client.ts）；公共设施 AgentRunProgress（SSE 观流）、MindmapView（导图）、LazyVideo（视频懒加载）、usePolling（轮询）、imageSrc（图片路径）、全局任务跟踪设施（agentRunStore/useRunTask/RunTaskBanner/AgentRunDock，见「前端公共设施」文档）；后端 `/api/v1/steps`、`/api/v1/sessions`、`/api/v1/agent-runs` 系列端点
- 被依赖: MainLayout 在 pathname 为 `/` 时为 WorkflowPage 提供布局与会话侧栏（视频会话 grouped 展示，见「前端公共设施」文档）
- 可复用组件: MaterialPickerModal/MentionImageInput 为通用素材选择/引用输入（Props 含 sessionId/pool 等，可脱离分镜场景复用）；MaterialGenerateModal 绑定分镜素材生成场景；material 组件均同时具名导出与 default export

## 注意事项

- **keep-alive 副作用**：4 步组件常驻挂载（display:none 隐藏），切换步骤不卸载——观流与本地草稿态（如 descDrafts）跨步骤保留；也因此 MindmapView 需要 ResizeObserver 零尺寸守卫（display:none 下渲染，见「前端公共设施」文档）。
- **Step6Videos 为遗留文件名**：历史 6 步时代命名，现为第 4 步「视频」；判断步骤结构以 StepNavigator.tsx:10-15 的 STEPS 注释（4 步）为准。
- **分镜形式三种为占位**：MODE_OPTIONS 中 first_frame/last_frame/first_last_frame 标注「暂未实现关联逻辑」，overlap 滑块、参考素材图、提示词生成均仅 all_reference 模式开放。
- **参考素材图为全量覆盖保存**：updateSegmentReferenceImages 每次提交完整数组（client.ts 注释：换图会清空该分镜已生成的提示词），前端追加/更换/移除/改描述都重放整个列表。
- **getMediaSrc 与 imageSrc 重复**：Step6Videos 组件内 getMediaSrc 与 `frontend/src/utils/imageSrc.ts` 逻辑相同（http(s) 原样、其余补 `/`），未复用工具函数。
- **Alert 的 title 属性**：StepSegmentManagement 底部 Alert 使用 `title` prop——antd v6 已将 Alert 的 message 更名 title（node_modules antd/es/alert/Alert.d.ts 中 message 标记 deprecated），此用法正确，阅读旧 antd 文档时勿误判为 bug。
- **步骤执行无全局编排**：workflowStore 不驱动任何步骤执行，各组件以 completed_steps 判定 canExecute 并提供前置步骤提示文案；步骤推进完全依赖后端会话状态 + refreshSession。
- **全局任务跟踪**：本工作台入队两类 kind（storyboard_outline / segment_prompt），进度呈现于右上角 AgentRunDock（MainLayout 挂载），跨菜单切换不丢；分镜提示词提交按钮的 confirming 守卫与 useRunTask.guardRunStart 双重防重复。
- **completeSegment 为单分镜粒度**：完成标记按 (sessionId, index, completed) 提交，不再一次整步完成。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析生成（feat/create_story 分支工作区状态） |
| 2026-09-21 | Step6Videos 整体重构（955 行）：分镜轨道 renderTrain（-24px 负 margin overlap 表现/连续勾选约束/虚线占位/longestRun 默认选最长连续段）、handleImport→handleGenerate→handleCancel 三段链路（importComfyUI/startComfyUIVideo/cancelVideos）、备份恢复与分镜详情 Modal、usePolling maxPolls 兜底，移除 regenerateVideos/regenerateSingleVideo 链路；StepStoryboardOutline 迁移全局任务跟踪（kind='storyboard_outline'，mindmap 变化渲染期切回预览）；StepSegmentManagement 提示词生成 confirming 守卫 + addRun（kind='segment_prompt'）+ completeSegment 单分镜完成；StepSelectEpisode 微调、MaterialPickerModal/ModelsPage/PromptsPage 小改；路由不变（/script、/、/models、/prompts） |
