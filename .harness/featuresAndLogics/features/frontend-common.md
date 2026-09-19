---
name: 前端公共设施
摘要: 跨页面复用的前端公共层，涵盖会话侧栏分组展示、主布局双轨会话管理、Agent 运行进度 SSE 流式消费与断线重连、提示词查看弹窗、思维导图渲染、视频懒加载、轮询 hooks 及统一 API 客户端与 SSE 请求工具。
tags: 前端, 公共组件, hooks, SSE, API客户端
---

# 前端公共设施

**状态:** 已完成
**最后更新:** 2026-09-19

## 功能概述

视频生成工作流与剧本创作两条业务线共用的前端基础设施：`SessionSider` 会话列表侧栏（平铺/二级分组两种形态）、`MainLayout` 布局骨架与双轨会话状态管理、`AgentRunProgress` 对 Agent 运行事件的 SSE 流式消费（断线重连 + seq 续传 + 取消）、`PromptViewerModal` 提示词查看/复制、`MindmapView` markdown 思维导图渲染、`LazyVideo`/`useLazyLoad` 视口懒加载、`usePolling` 轮询、`client.ts` axios 实例与各业务 API、`sse.ts` 的 `fetchSSE` 流式请求工具。这些设施由 `frontend/src/components/common/index.ts` 统一导出（组件部分），供各页面与步骤组件复用。

## 核心代码路径

- `frontend/src/components/common/SessionSider.tsx` — 会话侧栏组件，支持平铺与按 group.key 二级分组两种形态
- `frontend/src/components/layout/MainLayout.tsx` — 全局布局（Header/Sider/Content/Footer）+ 视频/剧本双轨会话状态管理
- `frontend/src/components/script/AgentRunProgress.tsx` — Agent 运行进度组件：SSE 消费、断线重连、seq 续传、取消
- `frontend/src/components/common/PromptViewerModal.tsx` — Agent 提示词查看弹窗（系统/用户提示词展示与复制）
- `frontend/src/components/common/MindmapView.tsx` — markdown 思维导图渲染（markmap-lib/markmap-view）
- `frontend/src/components/common/LazyVideo.tsx` — 视频懒加载组件（进入视口后才渲染 video）
- `frontend/src/hooks/useLazyLoad.ts` — IntersectionObserver 懒加载 hook
- `frontend/src/hooks/usePolling.ts` — 轮询 hook（savedCallback ref 模式）
- `frontend/src/api/client.ts` — axios 实例（baseURL `/api/v1`）+ sessionApi/stepApi/assetApi/modelApi/promptApi/uploadApi/scriptSessionApi/scriptStepApi/entityApi/agentRunApi
- `frontend/src/api/sse.ts` — `fetchSSE` 流式请求工具（GET/POST 自适应、按 `\n\n` 分帧解析）
- `frontend/src/components/common/index.ts` — 公共组件统一导出（LazyVideo、MindmapView、PromptViewerModal、SessionSider）

## 关键逻辑说明

### 1. SessionSider — 会话侧栏

Props 契约（`SessionSider (React.FC)`）：

- `sessions: Array<Pick<Session,'session_id'|'status'|'completed_steps'|'updated_at'> & {title?, group?: {key,title}, order?: number}>`
- 其余 props：`grouped?`、`loading`、`currentSessionId?`、`totalSteps`、`onCreate`、`creating?`、`onSelect(sessionId)`、`onDelete(sessionId)`、`onRefresh`

分组派生：

- `grouped=true` 时按 `s.group.key` 用 `Map` 派生二级分组，插入序即后端 `updated_at DESC` 序；无 `group` 的会话归入哨兵组 `UNGROUPED_KEY='__ungrouped__'`，组头标题固定「未选择剧本分集」。
- 组内排序 `(b.order ?? -Infinity) - (a.order ?? -Infinity)`，无 order 的排最后。

展开状态：

- `expandedKeys: Set<string>` 默认全部收起；`activeGroupKey`（当前选中会话所在组）在 useEffect 中依赖字符串值翻转时自动加入 `expandedKeys`——用户手动收起当前组、或刷新重拉时不会被重新弹开。

条目渲染：

- `renderItem(s, indented)` 平铺与分组二级复用（indented 时 paddingLeft 24）。
- 显示内容：title（缺省回退 `session_id.slice(0,8)`）、删除按钮（Popconfirm「确定删除此会话？」，stopPropagation）、session_id 前 8 位、状态 Tag（completed→success 已完成 / error→error 异常 / 其他→processing 进行中，由 statusColor 函数决定）、进度 `(completed_steps?.length || 0)/(totalSteps)` 步、`updated_at.toLocaleDateString()`。

组头与空态：

- 组头：`CaretRightOutlined` 旋转 90° 表示展开、组标题、scriptId 前 8 位、`(items.length)` 计数；空列表显示 antd Empty，loading 用 Spin 包裹。

### 2. MainLayout — 布局与双轨会话管理

- 结构：antd Layout：Header（标题「AI视频创作智能体」+ Menu 水平导航：`/script` 创作剧本、`/` 视频生成工作流、`/models` 模型管理、`/prompts` 提示词管理）+ 条件渲染 Sider width=280（仅 pathname 为 `/` 或 `/script` 时）+ Content{children} + Footer。
- 状态：视频/剧本双轨各自 useState（sessions 列表、loading、creating）；当前会话来自 zustand `useSessionStore`/`useScriptSessionStore` 的 currentSession；切换会话调 `store.loadSession(id)`（写 store，页面随 currentSession 重渲染并同步 URL）；选中相同 id 直接 return。
- legacy 过滤：`loadVideoSessions` 里 `setVideoSessions((result.sessions||[]).filter(s=>!s.legacy))`——legacy 会话直接隐藏。
- 删除行为：删除当前会话时调 `api.delete` 后 `setCurrentSession(null)` + `navigate(location.pathname,{replace:true})`（清 URL session_id），列表刷新由 currentSession 变化触发的 effect 完成；删除非当前会话则手动调 `loadVideoSessions`/`loadScriptSessions`。
- 加载时机：useEffect 依赖 `[isWorkflowPage, currentSession?.session_id, loadVideoSessions]`（剧本页同理）——进入页面或当前会话变化即拉列表；加载失败静默 catch，侧栏显示空态。
- SessionSider 两处用法（均在 MainLayout.tsx）：
  - 视频页 grouped（`videoSessionItems`：title=`第N集·集名` 或 episode_title，order=episode_number，group={key: script_session_id, title: script_title||'未命名剧本'}）；
  - 剧本页平铺（title=剧本名||'未命名剧本'）；两处 totalSteps 均传 4。

### 3. AgentRunProgress — Agent 运行进度（SSE 消费）

Props：`{ runId: string; onDone?: (event: AgentEvent) => void }`（React.FC，亦有 default export）。

断线重连：

- 常量 `MAX_RETRIES=6`、`RETRY_INTERVAL=2000`；`run()` 在 `while(!cancelled && !finished)` 循环中调 `fetchSSE(`/api/v1/agent-runs/${runId}/events${lastSeq ? `?seq=${lastSeq}` : ''}`, undefined /*GET*/, {onEvent, onError}, controller.signal)`。
- 每次 fetchSSE 返回（流断）后 retries+=1，`retries > 6` 时 `fail('连接中断，已停止重试')`；否则 sleep(2000) 重连。
- 收到 connected 事件时 retries=0（重置计数）。
- onError 中 `/^HTTP/.test(err.message)`（HTTP 层错误，如 run 不存在）直接 fail，不重试。

seq 续传：

- handleEvent 中 `if (ev.seq && ev.seq > lastSeq) lastSeq = ev.seq`；重连时以 lastSeq 作 query 参数从后端回放。

事件处理（switch ev.type）：

- connected → `setLabel(ev.label || '')`，retries=0；
- prompt → `setPrompt({systemPrompt: ev.system_prompt||'', userPrompt: ev.user_prompt||'', model: ev.model||''})`（赋值替换幂等，重连回放不重复累积）；
- thinking → `setThinking(prev+ev.delta)`（追加累积）；
- tool_use → `setThinking(prev+`\n[调用工具 ${ev.tool}]`)`；
- text_delta → `setText(prev+delta)`；
- result → ev.text 存在则 `setText(ev.text)`（整体替换）；
- done → finished=true，success 时 status 'success'，否则 'error' + errorMsg=ev.error||'运行失败'，调 `onDoneRef.current(ev)`；
- error → `fail(ev.message||'运行异常')`（fail 置 finished、status error、`onDone({type:'done',success:false,error:msg})`）。

生命周期：

- useEffect 依赖 `[runId]`，新 run 重置全部展示状态；onDone 存 ref 防止重建流；cleanup 置 cancelled=true 并 `controller.abort()`（fetchSSE 中 AbortError 不算错误直接 return）。

取消：

- handleCancel 调 `agentRunApi.cancel(runId)` = POST `/api/v1/agent-runs/{runId}/cancel`，`message.info('已请求取消')`；取消按钮仅 `status==='running'` 时显示。

UI：

- 状态行（Spin / CheckCircle 绿 / CloseCircle 红 + label||'Agent 运行' + 状态文案 进行中…/已完成/失败）+ prompt 存在时「查看提示词」按钮（PromptViewerModal）+ thinking 折叠 Collapse（pre maxHeight 200）+ text 区块（maxHeight 180）。

### 4. PromptViewerModal — 提示词查看

- Props：`{ open, onClose, systemPrompt?, userPrompt?, model? }`（亦有 default export）。
- Modal width=860、footer=null、destroyOnHidden，标题「Agent 提示词」+ model Tag。
- Tabs defaultActiveKey='user'：用户提示词页签恒显示（userPrompt||''），系统提示词页签仅 systemPrompt 真值时存在。
- 每页签：字符计数 + 复制按钮（`navigator.clipboard.writeText`，成功 `message.success('已复制')`/失败 `message.error('复制失败')`）+ pre 展示（fontSize 12、pre-wrap、maxHeight 55vh 滚动）。

### 5. MindmapView — 思维导图

- Props：`{ markdown: string; height?: number }`，height 默认 520。
- 实现：markmap-lib `Transformer` 模块级单例 `const transformer = new Transformer()`；markmap-view `Markmap.create(svg, {...deriveOptions({colorFreezeLevel: 2}), maxWidth: 280})`。
- useEffect 依赖 `[markdown]` 的渲染流程：
  1. markdown 或 svg 缺失直接 return；
  2. 若 `markmapRef.current.svg !== svg`（编辑模式卸载重挂 svg）先 destroy 旧实例重建；
  3. `Markmap.create` 不传 root，以避免卸载后内部 `setData().then(fit)`（svg 脱离 DOM 时 getBoundingClientRect 为 0 会算出 NaN transform）；
  4. `await setData(root)`（布局异步，等完成再 fit），fit 前检查 `svg.isConnected && rect.width>0 && rect.height>0`。
- 零尺寸守卫：步骤切换用 display:none 隐藏时 svg clientWidth/Height 为 0——若尺寸已就绪直接 render()；否则 `new ResizeObserver` 等任一 entry contentRect width/height>0 时 disconnect 并 render()，effect cleanup 时 disconnect。
- 卸载：独立 useEffect cleanup 调 `markmapRef.current?.destroy()`。
- 渲染失败：try/catch `console.error('思维导图渲染失败:', e)`。

### 6. LazyVideo / useLazyLoad — 懒加载

LazyVideo（`frontend/src/components/common/LazyVideo.tsx`）：

- Props：`{ src, poster?, style?, controls?=true, className?, placeholderHeight?=200 }`（注释称默认 300，实际代码默认 200——以代码为准）。
- `useLazyLoad({rootMargin:'160px', triggerOnce:true})`；未进入视口时渲染 #f5f5f5 占位 div（高 placeholderHeight + Spin「加载中...」）；进入后渲染 `<video src poster controls>`（width 100%、maxHeight placeholderHeight），fallback 文本「您的浏览器不支持视频播放」。

useLazyLoad（`frontend/src/hooks/useLazyLoad.ts`）：

- options `{ threshold?=0, rootMargin?='100px', triggerOnce?=true }`，返回 `{ ref: (node)=>void, isInView, hasBeenInView }`。
- ref 是 useCallback 回调（非 useRef .current 赋值）：节点变化时先 disconnect 旧 IntersectionObserver；`triggerOnce && hasBeenInView` 时不再观察；回调里 `setIsInView(entry.isIntersecting)`，进入视口 `setHasBeenInView(true)` 且 triggerOnce 时 disconnect；组件卸载 useEffect cleanup disconnect。

### 7. usePolling — 轮询

- 签名：`usePolling(callback: () => void | Promise<void>, { interval = 2000, enabled = true } = {})`。
- savedCallback ref 模式：useEffect 更新 `savedCallback.current`；主 useEffect 依赖 `[interval, enabled]`，enabled 时立即 tick() 一次 + `setInterval(tick, interval)`，cleanup clearInterval。
- 调用方（已逐行复核）：
  - `frontend/src/components/workflow/Step6Videos.tsx:97` — interval 3000，enabled: 有 pending 视频或后台生成中（hasPendingVideos || isBackgroundGenerating），刷新会话；
  - `frontend/src/components/script/StepEpisodeDesign.tsx:166` — interval 2000，enabled: `!!run?.active`（生成期间轮询分集/实体增量落库）；
  - `frontend/src/components/script/StepLookbook.tsx:68` — interval 2000，enabled: `runs.size > 0 || hasActiveImages`（有活跃 run 或 pending/processing 定妆照）。

### 8. apiClient — axios 实例与业务 API（`frontend/src/api/client.ts`）

- axios 实例：`axios.create({ baseURL: '/api/v1', timeout: 300000 (5min), headers Content-Type application/json })`；响应拦截器把错误归一为 `Error(error.response?.data?.detail || error.message || '请求失败')`；请求拦截器为透传空操作。
- API 清单：
  - sessionApi：create/list/get/delete（`/sessions`）；
  - stepApi：selectEpisode、generateStoryboardOutline→run_id（`data.data.run_id` 缺失抛 '未获取到 run_id'）、updateStoryboardOutline、updateSegmentConfig、getMaterialPool（`data?.data?.groups ?? []`）、updateSegmentReferenceImages、generateSegmentMaterial→run_id、getSegmentPromptContext、generateSegmentPrompt→run_id、completeSegmentManagement、generateVideos、regenerateVideos、cancelVideos、restoreVideosBackup；
  - assetApi：list/upload/remove（asset_type audio|image）；
  - modelApi：list/create/update/setDefault/remove（model_type image|chat）；
  - promptApi：list/get/save（markdown 覆盖写）；
  - uploadApi：uploadImage（multipart，返回 file_path+url）；
  - scriptSessionApi：create/list/get/delete（`/script-sessions`，create/list/get 返回 `data.data`）；
  - scriptStepApi：updateStoryLogic、updateOutline、generateEpisodes/regenerateEpisode→`data.data.run_id`、listEpisodes、updateEpisode、generateLookbook/completeLookbook/listLookbook（entity_id/task_status query 过滤）/regenerateLookbookImage→run_id、deleteLookbookImage；
  - entityApi：list（entity_type 过滤）/getReferences；
  - agentRunApi：cancel（POST `/agent-runs/{runId}/cancel`）。

### 9. fetchSSE — SSE 流式请求（`frontend/src/api/sse.ts`）

- 签名：`fetchSSE(url, body|undefined, handlers: {onEvent, onDone?, onError?}, signal?)` — body!==undefined 则 POST+JSON Content-Type，否则 GET（不用 EventSource：注释称避免其自动重连重复消费）。
- 解析：`resp.body.getReader` + TextDecoder stream 增量；buffer 按 `\n\n` 分割事件，尾段保留；每事件取所有 `data:` 行 slice(5).trim() 后 join('\n')；data==='[DONE]' 只置 doneReceived 不回调；其余 JSON.parse 后 handlers.onEvent，解析失败的行忽略。
- 错误语义：`!resp.ok || !resp.body` 时尝试 `JSON.parse(await resp.text())` 取 detail，否则 `` `HTTP ${status}` ``，throw；catch 中 `err.name==='AbortError'` 直接 return（主动取消不算错误）；正常结束调 onDone（[DONE] 与流关闭都算 done，doneReceived 变量实际未用于分支，末尾 `void doneReceived`）。

## 依赖与复用关系

- 依赖: antd（Layout/Menu/Sider、Spin、Popconfirm、Tag、Collapse、Empty、Tabs、Modal、message 等组件与反馈）、zustand（useSessionStore/useScriptSessionStore）、axios、markmap-lib + markmap-view（^0.18.12）、markdown-it（经 markmap-lib 传递依赖存在于 node_modules，非直接声明，见注意事项）
- 被依赖（调用点已逐行复核）: MainLayout 消费 SessionSider（两处：视频页 grouped / 剧本页平铺）；AgentRunProgress 消费 fetchSSE、PromptViewerModal、agentRunApi.cancel；MindmapView 用于 StepOutline（`frontend/src/components/script/StepOutline.tsx:281`）与 StepStoryboardOutline（`frontend/src/components/workflow/StepStoryboardOutline.tsx:271`）；LazyVideo 用于 Step6Videos（`frontend/src/components/workflow/Step6Videos.tsx:489/:549`）；usePolling 用于 Step6Videos/StepEpisodeDesign/StepLookbook（见第 7 节）；各业务 Step 组件消费 client.ts 各 API
- 可复用组件: `frontend/src/components/common/index.ts` 统一导出 LazyVideo、MindmapView、PromptViewerModal、SessionSider；hooks（useLazyLoad、usePolling）与工具（client.ts、sse.ts）按模块路径直接引用

## 注意事项

- **markdown-it 依赖漂移风险**：`frontend/src/components/script/StepEpisodeDesign.tsx:17` 直接 `import MarkdownIt from 'markdown-it'`，:46 `const md = new MarkdownIt({ html: false, breaks: true })`（html:false 依赖 markdown-it 默认转义）；但 `frontend/package.json` dependencies 无 markdown-it 条目，仅声明 markmap-lib/markmap-view ^0.18.12——markdown-it 靠 markmap-lib 传递依赖存在于 node_modules（markmap-lib 自身声明 markdown-it ^14.1.0）；`frontend/src/types/markdown-it.d.ts` 为手写最小 declare module（render + 4 个可选 options），因包无官方类型。若 markmap-lib 升级或移除 markdown-it 依赖，直接 import 将在 install/构建期断裂；建议显式声明 dependencies（此为风险描述，代码本身未处理）。
- **类型不一致**：modelApi.create 的 payload 类型标注 `model_type?: 'image'|'chat'`（漏 'agent'），update 则含 'agent'——类型定义不一致（代码事实）。
- **注释与代码不一致**：LazyVideo placeholderHeight 注释称默认 300，实际代码默认 200，以代码为准。
- **SSE 语义**：fetchSSE 不用 EventSource 是为避免其自动重连导致的重复消费；AbortError（主动取消）不算错误；`[DONE]` 与流关闭都算 done，doneReceived 变量实际未用于分支判断。
- **重连上限**：AgentRunProgress 重连上限 6 次（间隔 2s），收到 connected 事件重置计数；HTTP 层错误（如 run 不存在）不重试直接失败；prompt 事件为整体赋值替换（幂等，回放安全），thinking/text_delta 为增量追加，依赖 seq 续传从断点回放避免丢失。
- **seq 回放边界**：后端缓冲 `backend/core/agent_sdk/registry.py` 的 `MAX_EVENT_BUFFER=5000`（`deque(maxlen=5000)`，超限丢最旧）；`stream(run_id, from_seq)` 只回放缓冲中 `seq > cursor` 的事件——若断线期间事件超过 5000 条被截断，from_seq 之前的旧事件已不可得，后端静默跳过、无告警，前后端均未处理该极端场景（前端 lastSeq 续传假设事件仍在缓冲）。
- **思维导图零尺寸**：步骤切换（display:none）时 svg clientWidth/Height 为 0，MindmapView 内置 ResizeObserver 守卫等待非零尺寸再渲染；`Markmap.create` 不传 root 以规避卸载后 setData().then(fit) 算出 NaN transform。
- **legacy 会话与静默失败**：MainLayout 中 legacy 会话（s.legacy）被直接过滤隐藏；列表加载失败静默 catch，侧栏显示空态。
- **展开状态克制**：SessionSider 默认全部收起，仅 activeGroupKey 字符串值翻转时自动展开当前组，用户手动收起/刷新重拉不会被重新弹开。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修正 — scriptSessionApi 补全 list/get/delete；usePolling 三个调用点与 LazyVideo/MindmapView 调用点逐行复核并落实（移除 3 处「待补充」）；seq 回放边界落实至 backend/core/agent_sdk/registry.py（MAX_EVENT_BUFFER=5000 静默截断语义） |
