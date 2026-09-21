---
name: SSE 事件流协议逻辑
摘要: SSE 按 seq 增量推送 AgentRun 事件，支持断线重连续传、取消与并发排队（MAX_CONCURRENT_RUNS=5）
tags: SSE, 事件流, 断线重连, AgentRun
---

# SSE 事件流协议逻辑

**最后更新:** 2026-09-21

## 逻辑概述

耗时 agent 生成任务不占用 HTTP 请求同步执行：生成类 POST 接口经 `backend/deps.py` 的 `run_agent_endpoint(label, factory)`（原 `start_agent_run` 改名，签名不变；返回 `{"success": True, "data": {"run_id": ...}}`）调 `get_run_registry().start(label, factory)`，立即返回 12 位 hex `run_id`。run 生命周期 `status: queued → running → done`：`start()` 后 run 不一定立即执行——并发超限时先入队，业务 factory 由常驻 worker 协程领取后执行。执行期间 ClaudeSDKClient 流式消息归一为 `AgentEvent`（`backend/core/agent_sdk/events.py`），经 `RunHandle.emit` 写入每 run 独立的 `deque` 事件缓冲（maxlen=5000），`seq` 从 1 起单调递增（`_seq` 初始 0，emit 先自增再入缓冲）。

观流走 `GET /api/v1/agent-runs/{run_id}/events?seq=N`（`backend/api/v1/agent_runs.py`，APIRouter 经 main.py include_router 挂载于 `/api/v1/agent-runs`）：`seq` 为客户端已消费的最大事件序号，用于断线重连增量续传，默认 0 即全量回放。响应为 `StreamingResponse(gen(), media_type='text/event-stream')`，事件序列固定为 `connected` → 逐业务事件（dict 已含 seq，自然含排队期的 `queued` 与领取时的 `started`）→ `done` 终态 → `data: [DONE]` 哨兵；所有 JSON `ensure_ascii=False`，行以 `\n\n` 结尾。

实时性由 `asyncio.Condition` 驱动：`registry.stream` 无新事件且 run 未结束时 `await cond.wait()` 挂起，`emit` 与 `_run` 收尾时持锁 `notify_all` 唤醒。前端 `fetchSSE`（`frontend/src/api/sse.ts`）手写 fetch + ReadableStream 解析而非 EventSource：POST 端点无法用 EventSource，GET 事件端点也用同一实现以避免 EventSource 自动重连导致的重复消费。`AgentRunProgress.tsx`（现为 AgentRunDock 弹窗内进度渲染器）维护 `lastSeq` 游标，配合重试上限（MAX_RETRIES=6、间隔 2000ms）实现断线重连增量续传。取消为协作式且区分阶段：执行中 `POST /{run_id}/cancel` → `interrupt_event.set()` → wrapper 内 interrupt 监听协程 `await client.interrupt()`，agent 进程自然终止，不直接 kill task；排队中 cancel 则立即落终态、factory 不执行（见下文）。registry 为进程内单例、无持久化，重启即失。

## 关键流程

**生成与观流主链路**

1. 启动 run — 前端调生成类 POST 接口（如 `/steps/{session_id}/storyboard-outline/generate`、`/script-sessions/{session_id}/outline/generate`）→ 定义 `factory(on_event, interrupt)` 后调 `run_agent_endpoint(label, factory)`（`backend/deps.py`，原 start_agent_run 改名）→ `AgentRunRegistry.start(label, factory)`：先 `_cleanup()`，生成 `run_id=uuid.uuid4().hex[:12]`（12 位 hex），创建 RunHandle（status='queued'）存入 `_runs` 并立即返回 run_id（`handle.task` 字段已删除）
2. 领取执行 — worker 协程领取后 `_run(handle, factory)` await `factory(handle.emit, handle.interrupt_event)`（factory 签名 `(on_event, interrupt_event) -> Awaitable[dict]`）；factory 内调 wrapper 的 run_agent/run_conversation，ClaudeSDKClient 流式消息归一为 AgentEvent（构造处见 `backend/core/agent_sdk/wrapper.py`：prompt 事件在 LLM 调用前流出最终渲染提示词 system_prompt/user_prompt/model；流式 delta → thinking/text_delta；完整 assistant 消息与流式增量去重后补发；tool_use/tool_result 中 result_preview 按 `text[:50000]` 截断）
3. 事件入缓冲 — `RunHandle.emit(event)`：`_seq` 自增 1 → `events.append((seq, event))`；有运行 loop 则 `loop.create_task(_notify())` 持 cond 锁 `notify_all`；无运行 loop（RuntimeError）直接 return（事件仍入 deque，靠消费侧轮询/后续 notify 兜底）
4. 建立观流 — 前端 GET `/api/v1/agent-runs/${runId}/events`（初始 lastSeq=0 不带 seq 参数=全量回放）→ `stream_run_events`：run 不存在时 `HTTPException 404 detail='run 不存在或已过期: {run_id}'`，否则返回 `StreamingResponse(gen(), media_type='text/event-stream')`
5. connected 握手 — `gen()` 先 yield `{'type':'connected','label':handle.label,'last_seq':handle._seq}`
6. 事件推送 — `gen()` 内 `async for registry.stream(run_id, from_seq=seq)`：stream 持 cond 锁收集 `seq > cursor` 的现存 pending（cursor 推进至末条 seq），锁外逐条 yield `ev.to_dict(seq)`；无 pending 且未 done → `await cond.wait()` 后 continue；无且 done → return（终态 done/[DONE] 由端点层补充）；`gen()` 逐事件 yield data 行；stream 抛 KeyError 时 `gen()` yield `{'type':'error','message':...}`
7. 终态收尾 — run 结束后 `gen()` yield `{'type':'done','success':handle.success,'error':handle.error,'result':handle.result_data}`，最后 yield `data: [DONE]` 哨兵；所有 JSON `ensure_ascii=False`、行以 `\n\n` 结尾
8. 前端解析 — `fetchSSE` 以 `resp.body.getReader()` + `TextDecoder(stream:true)` 增量解码：buffer 按 `\n\n` 分割 SSE 事件（最后一段留作 buffer），每段取 `data:` 开头的行（`slice(5).trim()`，多行 join `'\n'`）；`data==='[DONE]'` 不回调，其余 JSON.parse 成功调 `handlers.onEvent`，解析失败静默忽略
9. 事件分发 — `AgentRunProgress.handleEvent` 先推进游标 `if (ev.seq && ev.seq > lastSeq) lastSeq = ev.seq`，再按 type switch：connected→setLabel 且 retries=0；queued→显示排队文案「排队中（前面还有 N 个任务）」（N=queue_position）；started→`agentRunStore.markRunRunning`；prompt→setPrompt({systemPrompt:ev.system_prompt, userPrompt:ev.user_prompt, model:ev.model})（赋值替换幂等）；thinking→thinking += delta；tool_use→thinking += '\n[调用工具 {tool}]'；text_delta→text += delta；result→ev.text 时整体 setText 覆盖；done→finished=true、按 ev.success 置 status success/error、防重复回调 onDoneRef；error→fail(ev.message)

**排队与并发（MAX_CONCURRENT_RUNS=5）**

1. 并发上限 — `MAX_CONCURRENT_RUNS=5`（registry.py:22）：同时处于 running 态的 run 数上限；`start()` 后 run 不一定立即执行
2. 入队 — 超出并发上限的 run 发 `queued` 事件（含 `queue_position`——排队位置，计算时排除已取消者）后进入 `_pending` deque
3. 领取 — 5 个常驻 worker 协程 FIFO `_pending.popleft()`（跳过排队期间已取消的 run）；领取时置 `status="running"` 并 emit `started` 事件（前端据此把 run 标记为运行中）
4. 排队中取消 — `cancel` 对排队中的 run：立即落终态（done、success=False、error="已取消（排队中）"）+ emit error 事件，factory 不执行——区别于执行中 cancel 走 interrupt_event 自然终止

**断线重连**

1. 重连循环 — useEffect（runId 变化时重置状态）内 `while (!cancelled && !finished)` 循环调 `fetchSSE(\`/api/v1/agent-runs/${runId}/events${lastSeq ? \`?seq=${lastSeq}\` : ''}\`, undefined, handlers, controller.signal)`
2. 计数与重试 — 流结束（fetchSSE resolve）且未 finished → retries+=1；超过 MAX_RETRIES=6 → `fail('连接中断，已停止重试')`；否则 sleep(RETRY_INTERVAL=2000) 后重连
3. 计数重置 — 收到 connected 事件即 retries=0
4. 错误分类 — onError 中 `/^HTTP/.test(err.message)`（如 404 run 不存在）直接 fail 不重连；其余（读流网络中断）交由外层重连循环处理
5. 卸载清理 — 组件卸载时 cancelled=true + controller.abort()；fetchSSE 对 AbortError 静默 return

**取消**

1. 请求取消 — 前端 `agentRunApi.cancel(runId)` → POST `/api/v1/agent-runs/{run_id}/cancel`（cancel_run 调 `registry.cancel(run_id)`，返回 `{'success':ok,'message':'已请求取消'|'run 不存在或已结束'}`）
2. 协作终止 — `cancel` 对不存在或已 done 的 run 返回 False；对排队中的 run 立即落终态（done、success=False、error="已取消（排队中）"）+ emit error 事件，factory 不执行；对执行中的 run `interrupt_event.set()` → wrapper 内 interrupt 监听协程 `await client.interrupt()`，agent 进程自然终止（不直接 kill task）→ CancelledError → `_run` 置 success=False、error='已取消' 并 raise，finally 置 done=True + notify_all → 前端收到 done 终态

**SSE 直跑（不经 registry，backend/core/agent_sdk/direct.py）**

1. `sse_direct_response(coro_factory)` — 自 script_sessions.py 的 `_sse_direct` 抽出为通用能力（router 只留 HTTP 包装），SSE 请求内直跑编排，不经 registry 排队
2. 语义不变 — 内部 asyncio.Queue 中转事件逐个 `to_sse(0)` yield（seq 恒 0，无断线重连语义）；无 connected/done 帧，以 final/final_err 帧 + `data: [DONE]` 哨兵收尾
3. 断开处理 — finally 检测客户端断开：`interrupt_event.set()` 优雅终止 + `asyncio.wait_for(asyncio.shield(task), 5s)` 宽限后 `task.cancel()` 强杀
4. 消费方 — `frontend/src/components/script/StepIdeationChat.tsx` 不变（POST `/api/v1/script-sessions/{session_id}/ideation/message`、`/ideation/finalize`）

**前端全局任务坞消费（AgentRunDock）**

1. `AgentRunProgress` 演变为 `AgentRunDock`（`frontend/src/components/layout/AgentRunDock.tsx`，全局任务坞）弹窗内的进度渲染器：Dock 由 MainLayout 全局挂载，任一路由下提交的生成 run 均可回看
2. 每 run `forceRender` 保活：Modal 收起不卸载组件，SSE 连接不断流
3. 排队态展示 — 初始 status 'queued'；收到 queued 事件显示「排队中（前面还有 N 个任务）」（N=queue_position）；started 事件触发 `agentRunStore.markRunRunning`；done 防重复触发 onDone
4. 配套 — `frontend/src/hooks/useRunTask.ts` 封装提交生成任务的通用流程；`frontend/src/components/common/RunTaskBanner.tsx` 为页面内任务横幅
5. `frontend/src/types/index.ts` 的 AgentEvent 前端类型新增 `'queued'|'started'` 与 queue_position 字段

## 涉及代码

- `backend/deps.py` — `run_agent_endpoint(label, factory)`（原 start_agent_run 改名）：统一提交 agent 运行到 registry，返回 `{"success": True, "data": {"run_id": ...}}`
- `backend/api/v1/agent_runs.py` — SSE 观流端点（APIRouter 经 main.py include_router 挂载于 `/api/v1/agent-runs`）：`GET /{run_id}/events`（stream_run_events + gen 事件序列）、`GET /{run_id}`（get_run 轮询兜底，返回 `{'success':True,'data':handle.to_dict()}`，to_dict 含 run_id/label/status/done/success/error/result/last_seq，404 同上）、`POST /{run_id}/cancel`（cancel_run）
- `backend/core/agent_sdk/registry.py` — `AgentRunRegistry`/`RunHandle`：start/_run/emit/stream/cancel/get/_cleanup；`MAX_CONCURRENT_RUNS=5`（并发上限，registry.py:22）+ `_pending` deque + 5 个常驻 worker 协程（FIFO 领取）；run status `queued→running→done`；`MAX_EVENT_BUFFER=5000`（每 run 事件缓冲 deque maxlen）、`MAX_RUNS=200`（注册表容量）；模块级 `_registry` + `get_run_registry()` 惰性创建进程内单例
- `backend/core/agent_sdk/events.py` — `@dataclass AgentEvent`（type/delta/id/tool/input/result_preview/text/session_id/usage/message/system_prompt/user_prompt/model/queue_position，字段全带默认值，input/usage 用 `field(default_factory=dict)`，`queue_position: int = -1`）；type 取值：thinking/text_delta/tool_use/tool_result/result/error/prompt/queued/started；`to_dict(seq)`（seq 非 None 加 'seq'，其余字段仅非空写入，queue_position>=0 时输出）、`to_sse(seq)`（agent_runs.py 的 gen() 未用此方法，而是自行 json.dumps(to_dict 结果)）
- `backend/core/agent_sdk/direct.py` — sse_direct_response：SSE 请求内直跑编排（自 script_sessions.py 的 _sse_direct 抽出，不经 registry）
- `backend/core/agent_sdk/wrapper.py` — AgentEvent 各 type 的实际构造处：run_agent/run_conversation 在 LLM 调用前流出 prompt 事件（最终渲染的 system_prompt/user_prompt/model，模型名取 env ANTHROPIC_MODEL）；流式消息 → thinking/text_delta/tool_use/tool_result；完整 assistant 消息与流式增量去重后补发；tool_result 的 result_preview 超 50000 字符截断（`text[:50000]`）；interrupt 监听协程 await client.interrupt() 实现协作取消
- `frontend/src/api/sse.ts` — `fetchSSE(url, body, handlers, signal?)`：body!==undefined 则 POST + Content-Type: application/json + JSON.stringify(body)，否则 GET；非 2xx 尝试 JSON.parse(resp.text()) 取 detail（否则 'HTTP {status}'）throw Error；SSEHandlers 为 onEvent 必填/onDone/onError 可选
- `frontend/src/components/script/AgentRunProgress.tsx` — GET 观流消费方（现为 AgentRunDock 弹窗内进度渲染器）：lastSeq 游标、MAX_RETRIES=6/RETRY_INTERVAL=2000ms 重连循环、事件 switch 分发（含 queued/started）、错误分类、取消
- `frontend/src/components/layout/AgentRunDock.tsx` — 全局任务坞（MainLayout 挂载）：每 run forceRender 保活（Modal 收起不卸载、SSE 不断流）、排队文案与 markRunRunning
- `frontend/src/stores/agentRunStore.ts` / `frontend/src/hooks/useRunTask.ts` / `frontend/src/components/common/RunTaskBanner.tsx` — run 状态 store（markRunRunning 等）/提交任务通用 hook/页面内任务横幅
- `frontend/src/components/script/StepIdeationChat.tsx` — POST 直跑 SSE 消费方：fetchSSE POST `/api/v1/script-sessions/{session_id}/ideation/message`（对话）与 `/api/v1/script-sessions/{session_id}/ideation/finalize`（定稿）
- `frontend/src/api/client.ts` — `agentRunApi` 引用 agent-runs 端点（cancel 等）
- `tests/manual/test_agent_run_queue.py` — 排队语义回归（约 80 行纯 asyncio 无 LLM：入队/领取/排队中取消）

## 相关功能

- 构思对话（StepIdeationChat，POST 直跑 SSE：`/script-sessions/{session_id}/ideation/message`、`/script-sessions/{session_id}/ideation/finalize`）
- 后台生成类接口（经 `backend/deps.py` 的 `run_agent_endpoint` 启动 agent run 的接口，如分镜大纲 `/steps/{session_id}/storyboard-outline/generate`、脚本大纲 `/script-sessions/{session_id}/outline/generate` 等）

## 注意事项

- 事件缓冲为每 run `deque(maxlen=5000)`（MAX_EVENT_BUFFER），超限丢最旧事件；丢事件无任何标记给客户端，stream 回放 from_seq 大于现存最小 seq 时存在事件缺口，代码未处理该边界
- `MAX_RUNS=200`：`_cleanup` 按 created_at 升序删除最早 done 的 run 至 len<=200；若全部 run 未完成则不删，`_runs` 可超 200（代码现状）
- registry 进程内单例、无持久化，重启即失；run 不存在时 events 观流与 get_run 均返回 404 `detail='run 不存在或已过期: {run_id}'`
- `emit` 的"无运行 loop 时 return"分支在当前调用链（asyncio 后台 task 内同步调用）是否实际可达未验证（待补充）
- 重连重复消费风险：thinking/text_delta 为增量拼接；重连回放从 from_seq（=lastSeq，已更新到最新）开始则无重复；seq 落后于已消费位置时正常续传；deque 超限丢最旧后 from_seq 指向已被丢弃的 seq 之后仍正常（stream 只发 seq>cursor 的现存事件），但旧事件永久丢失
- 事件处理语义：prompt 为赋值替换幂等（断线重连回放不重复累积）；thinking/tool_use/text_delta 为增量拼接；result 的 ev.text 整体覆盖；done 按 ev.success 定终态
- fetchSSE 错误语义：`err.name==='AbortError'` 直接 return（主动取消不算错误、也不调 onDone）；其他错误调 onError 后 return（不调 onDone）；正常结束才调 onDone；`doneReceived` 变量仅 void 引用未参与逻辑
- `to_dict` 其余字段仅非空时写入（空字符串/空 dict 过滤）以减小 SSE 体积；`to_sse()` 存在但 `agent_runs.py` 的 gen() 未使用
- done 事件中 `result`（result_data）的具体业务 schema 由各业务 factory 决定，协议层不定型
- 轮询兜底：`GET /{run_id}`（get_run）返回 handle.to_dict()（run_id/label/status/done/success/error/result/last_seq），可在 SSE 不可用时轮询终态与排队状态
- 排队语义：start() 立即返回 run_id 但 run 可能仍在 `_pending` 排队（MAX_CONCURRENT_RUNS=5）；queue_position 计算排除已取消者；排队中 cancel 立即落终态不执行 factory（error="已取消（排队中）"），执行中 cancel 走 interrupt_event 自然终止（error='已取消'）——两条取消路径的 done.error 文案不同
- SSE 直跑（direct.py 的 sse_direct_response）seq 恒 0、无 connected/done/断线重连语义，与 registry 观流是两套并存的 SSE 形态

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修正 — `deps.launch_agent_run` 更正为 `backend/deps.py` 的 `start_agent_run`；seq 起始值更正为 1；`/steps/{sid}` 更正为 `/steps/{session_id}`；prompt 分发字段映射精确化；wrapper.py 构造细节（50000 截断/去重/interrupt）已核实落实 |
| 2026-09-21 | registry 新增并发排队（MAX_CONCURRENT_RUNS=5、_pending/worker、status queued→running→done、删除 handle.task）；AgentEvent 新增 queued/started 与 queue_position；_sse_direct 抽出为 direct.py 的 sse_direct_response；前端 AgentRunDock 全局任务坞消费；新增 tests/manual/test_agent_run_queue.py 回归 |
