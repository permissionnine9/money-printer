---
name: api-and-sse-conventions
摘要: 统一 ApiResponse 同形包络与 detail 错误体；业务异常统一继承 WorkflowError（backend/core/errors.py）经 main.py 单个全局 handler 映射状态码；长任务 run_id 立返且经 registry FIFO 排队（MAX_CONCURRENT_RUNS=5，queued/started 事件），SSE 按 seq 断线续传，前端 fetchSSE 手写解析、AgentRunDock 全局观流。
tags: [API, SSE, 响应包络, 异常处理, agent-runs, fetchSSE, 运行队列, AgentRunDock, useRunTask]
---

# API 与 SSE 编码约定

**类别:** 实现规范
**最后更新:** 2026-09-21

## 原因

项目 API 层由三条既有实现主轴推导出本规范：**统一响应包络**、**集中式业务异常处理（WorkflowError 单基类）**、**长任务 run_id 立返 + registry 排队与 SSE 观流解耦**。以下约定均直接来自当前源码实现，不做推测。

### 1. 统一响应包络（ApiResponse 同形 dict）

`backend/schemas/common.py`：

```python
class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    message: Optional[str] = None
```

- JSON 形态恒为 `{"success": bool, "data": T|null, "message": str|null}`。
- **采用现状（已核对）**：`ApiResponse` 目前仅是 schema 定义，`backend/api/v1/` 下无任何路由导入它；路由实际以裸 dict 返回**同形** JSON——成功 `{"success": True, "data": ...}`，写操作 `{"success": ok, "message": ...}`（如 script_sessions.py、agent_runs.py 全部端点）。新路由按此形态返回 dict 即可，不必导入模型。

### 2. 错误体统一为 {"detail": ...}

业务异常统一收口到基类 **`WorkflowError`**（backend/core/errors.py，13 行）：`WorkflowError(Exception)`，构造参数为 message + `status_code: int = 400`（挂实例属性）。

backend/main.py 现为**单个** `@app.exception_handler(WorkflowError)`（原按异常类分别注册的写法已收敛）：

| 业务异常 | 定义位置 | status_code |
|------|------|------|
| WorkflowError（基类） | backend/core/errors.py | 构造参数 `status_code: int = 400` |
| ScriptWorkflowError | backend/core/agents/script_workflow.py | 继承 WorkflowError；自有 status_code `__init__` 样板已删除（基类承担） |
| StoryboardError | backend/core/agents/storyboard.py | 同上 |

- 返回 `JSONResponse(status_code=getattr(exc, "status_code", 400), content={"detail": str(exc)})`：状态码由异常携带，缺省 400。业务代码 raise 时可显式指定（如 script_workflow.py `raise ScriptWorkflowError(f"分集不存在: {episode_id}", status_code=404)`）。
- **路由层无需逐个 try/except**：直接 raise 业务异常即可；新增业务异常只要继承 WorkflowError 即自动被全局 handler 覆盖，无需再注册 handler、也无需自带 status_code 构造样板。
- 其他错误沿用 FastAPI 惯用形态：`backend/api/v1/agent_runs.py` 对不存在的 run 直接 `raise HTTPException(404, detail=f"run 不存在或已过期: {run_id}")`，即错误体为 `{"detail": ...}`，前端 `fetchSSE` 解析 `parsed.detail`。

### 3. 应用骨架（backend/main.py）

| 项 | 约定 |
|------|------|
| CORS | `allow_origins=["http://localhost:5173", "http://localhost:3000"]`，`allow_credentials=True`，`allow_methods/headers=["*"]` |
| 静态资源 | `app.mount("/static", StaticFiles(directory="static"), name="static")` |
| 路由挂载 | 8 个子路由 prefix 均为 `/api/v1/*`：sessions / steps / uploads / assets / models / prompts / script_sessions / agent_runs |
| lifespan | 启动时调用 backend/config.py 的 `override_src_config()` 打印实际生效的模型配置 |

### 4. 长任务：run_id 立返、FIFO 排队与观流解耦

**启动侧（backend/deps.py）**：`run_agent_endpoint(label, factory)`（**原 `start_agent_run` 已改名**，签名不变）调 `get_run_registry().start(label, factory)` 立即返回，响应统一为 `{"success": True, "data": {"run_id": run_id}}`。

**registry（backend/core/agent_sdk/registry.py）—— Agent 运行队列（FIFO + 并发上限）**：

- `MAX_CONCURRENT_RUNS = 5`（registry.py:22）：进程内最多 5 个 run 同时执行。
- `AgentRunRegistry.start` 流程：`_cleanup()` → `run_id = uuid.uuid4().hex[:12]`（12 位 hex）→ handle append 进 `_pending` deque（**不再直接 create_task**；先进 deque 保留了 cancel 的即时性）→ emit `AgentEvent(type="queued", queue_position=N)` → 立返 run_id。**提交 ≠ 执行**：高峰期 run 会先排队。
- `_ensure_workers()` 惰性启动 5 个常驻 worker 协程（模块持强引用防 GC），按 FIFO `popleft` 领取（跳过排队期间已被取消的 run）。
- `_run` 领取任务时置 `status="running"` 并 emit `started` 事件；finally 落 `status="done"`。执行语义不变：成功 → `result_data = data or {}`、`success=True`；`asyncio.CancelledError` → `success=False`、`error="已取消"` 后 re-raise；其他异常 → `success=False`、`error=str(e)` 并 `logger.exception`；`cond.notify_all()`。
- **RunHandle 生命周期**：新增 `status` 字段（`queued → running → done`）；`to_dict()` 输出 status；`task` 字段已删除（worker 池模式不再向外暴露 task）。
- **cancel() 分叉**：排队中（status="queued"）→ 立即落终态（done、success=False、error="已取消（排队中）"）并 emit error 事件，**factory 不执行**；执行中（running）→ 仍 `interrupt_event.set()`，由 agent 进程**自然终止**。
- **注册表与容量**：`get_run_registry()` 为进程内全局单例（模块级 `_registry`），`_runs: dict[run_id, RunHandle]`；**重启即失、无持久化**。`MAX_EVENT_BUFFER=5000`（每 run 事件 `deque(maxlen=5000)`，超限丢最旧）、`MAX_RUNS=200`（超出时按 `created_at` 清理最早完成的 run，仅清 `done` 的）——均不变。

**RunCoroFactory 签名**：`Callable[[on_event: Callable[[AgentEvent], None], interrupt_event: asyncio.Event], Awaitable[dict]]` —— 业务协程经 `on_event` 回调发事件，返回的 dict 作为 `result_data`。

**RunHandle 字段**：`run_id, label, created_at, status(queued/running/done), events: deque[(seq, AgentEvent)]（maxlen=5000）, _seq（从 0 起、emit 时自增）, done/success/error/result_data（结束后供轮询）, interrupt_event(asyncio.Event), cond(asyncio.Condition)`。

**emit**：`_seq+=1` → `events.append((seq, event))` → 若有运行中 loop 则 `create_task(_notify())`（`cond.notify_all`）；无 loop 时静默返回，由消费侧 `cond.wait` 轮询兜底。

### 5. SSE 观流协议（GET /api/v1/agent-runs/{run_id}/events?seq=N）

实现：`backend/api/v1/agent_runs.py`，`text/event-stream`（StreamingResponse）。事件序列不变：

| 顺序 | 事件 | 说明 |
|------|------|------|
| 1 | `data: {"type":"connected","label":...,"last_seq":handle._seq}` | 连接即发 |
| 2 | `data: {AgentEvent.to_dict(seq)}` | 回放 + 实时事件（`json.dumps` `ensure_ascii=False`） |
| 3 | `data: {"type":"done","success":...,"error":...,"result":handle.result_data}` | 终态，前端据此刷新 store |
| 4 | `data: [DONE]` | 流结束哨兵 |

- 流中会**自然出现 `queued` / `started` 事件**（由 registry 发出，非业务协程）：`queued` 带 `queue_position`（排在第几位），`started` 表示 worker 已领取、开始执行。
- **seq 语义**：查询参数 `seq: int = 0` 表示客户端已消费的最大事件序号；断线重连增量续传，默认 0 全量回放。`registry.stream(run_id, from_seq=seq)` 按 seq 顺序先回放缓冲中 `seq > cursor` 的事件，再实时等 cond。
- **错误**：run 不存在 → `HTTPException(404)`；流中 `KeyError` → 发 `{"type":"error","message":...}` 事件后**仍继续发 done + [DONE]**。
- **业务事件类型**：`AgentEvent`（backend/core/agent_sdk/events.py）`type: prompt / thinking / text_delta / tool_use / tool_result / result / error / queued / started`。dataclass 新增 `queue_position: int = -1`，`to_dict(seq)` 在 `queue_position >= 0` 时输出该字段；其余逻辑不变（`seq` 非 None 时注入，其余字段仅在非空时加入以过滤空字段减小 SSE 体积）；`to_sse(seq)` = `f"data: {json.dumps(self.to_dict(seq), ensure_ascii=False)}\n\n"`。

### 6. run 轮询兜底与取消

| 端点 | 行为 |
|------|------|
| `GET /api/v1/agent-runs/{run_id}` | 404 或 `{"success": True, "data": handle.to_dict()}`；`to_dict = {run_id, label, status(queued/running/done), done, success, error, result, last_seq}` |
| `POST /api/v1/agent-runs/{run_id}/cancel` | `registry.cancel(run_id)`：handle 不存在或已 done 返回 False；**排队中立即落终态、factory 不执行**（见第 4 节）；执行中 `interrupt_event.set()`，由 agent 进程**自然终止**；响应 `{"success": ok, "message": ...}` |

### 7. SSE 直跑形态（POST SSE，不经 registry）

- 端点：`POST /api/v1/script-sessions/{session_id}/ideation/message` 与 `.../ideation/finalize`（backend/api/v1/script_sessions.py 只留 HTTP 包装）；核心实现已抽为 **backend/core/agent_sdk/direct.py 的 `sse_direct_response(coro_factory)`**（经 `agent_sdk/__init__.py` 导出），在 SSE 响应内直接跑 agent，**不经 registry、断开即取消**。
- 前端 `fetchSSE` 以 POST + JSON body 消费（EventSource 不支持 POST）。
- **直跑事件序列（已核对）**：`AgentEvent.to_sse(0)`（seq 恒 0，无 seq 续传语义；**无 connected/done 事件**；内部经 `asyncio.Queue` 中转 agent 事件到 SSE 生成器）→ 终态 `data: {"type":"final","data":payload}` 或 `{"type":"error","message":...}` → `data: [DONE]`。
- **断开取消语义**：客户端断开时先 `interrupt_event.set()` 优雅终止，`asyncio.wait_for(asyncio.shield(task), timeout=5)` 给 5 秒宽限，超时才 `task.cancel()`。
- 前端消费方为 StepIdeationChat（frontend/src/components/script/StepIdeationChat.tsx）。

### 8. 前端 SSE 客户端（frontend/src/api/sse.ts）

`fetchSSE(url, body, handlers, signal)`：

- `body !== undefined` → POST + `Content-Type: application/json`；否则 GET。**不用 EventSource**（POST 不可用；GET 也用手写实现以避免自动重连重复消费）。
- 解析：`ReadableStream` `getReader` + `TextDecoder(stream: true)` 累积 buffer；按 `'\n\n'` 切分事件；每事件取以 `data:` 开头的行，`slice(5).trim()` 后 `join('\n')`；`data === "[DONE]"` 只置 doneReceived 不回调；其余 `JSON.parse` 后回调 `onEvent`，非 JSON 行忽略。
- handlers：`onEvent`（必选）/ `onError`（网络错误或非 2xx）/ `onDone`（**仅在读循环正常结束、即服务端关闭流后调用**；收到 [DONE] 哨兵本身不触发回调，AbortError 时直接 return 也不回调 onDone/onError）。
- 非 2xx：尝试 `JSON.parse` 响应体取 `parsed.detail` 作为错误 message，失败回退 `'HTTP {status}'`。
- abort：`AbortError` 视为主动取消直接 return，不算错误；调用方持 AbortController 取消。

**观流消费（AgentRunDock 全局任务坞 + AgentRunProgress）**：

- **AgentRunDock（全局任务坞，frontend/src/components/layout/AgentRunDock.tsx）**：MainLayout 全局挂载；运行状态收口在 **agentRunStore**（frontend/src/stores/agentRunStore.ts，zustand）；每个 run 一个 forceRender 保活 Modal —— **收起不卸载、SSE 不断流**，多个 run 可同时观流、独立收起。
- **AgentRunProgress**（frontend/src/components/script/AgentRunProgress.tsx）：现为 AgentRunDock 弹窗内的进度渲染器。`GET /api/v1/agent-runs/{runId}/events?seq={lastSeq}` 观流；读流中断后重连最多 6 次（`MAX_RETRIES=6`）× 2s（`RETRY_INTERVAL=2000`），收到 connected 事件会将重试计数清零；seq 续传幂等去重（`ev.seq > lastSeq` 才推进，prompt 事件为赋值替换不累积）；`onError` 中 message 匹配 `/^HTTP/` 的 HTTP 层错误（如 run 404）直接失败不重连；可取消 run。排队感知：初始 status 'queued'、排队文案「排队中（前面还有 N 个任务）」（取 queue_position）、started 事件触发 `markRunRunning`、done 防重复 onDone。
- **useRunTask**（frontend/src/hooks/useRunTask.ts）：`guardRunStart`（POST 在途或 store 中已有任务时以 antd `message.warning` 拦截，防重复发起）/ `useRunActive` / `useRunError`；配套 **RunTaskBanner**（frontend/src/components/common/RunTaskBanner.tsx）通用横幅组件展示进行中任务。

**前端 AgentEvent 类型**：`type: connected|prompt|thinking|text_delta|tool_use|tool_result|result|final|done|error|queued|started`，字段含 `seq`、`delta/text`、`label/last_seq`、`queue_position`（queued）、`system_prompt/user_prompt/model`、`data`（final）、`success/error/result`（done）（比后端业务事件类型更宽，含协议层 connected/done 与 final）。

## 适用范围

- `backend/api/v1/` 全部 8 个子路由（sessions / steps / uploads / assets / models / prompts / script_sessions / agent_runs）
- `backend/main.py`（全局异常处理与应用骨架）、`backend/schemas/common.py`（响应包络）、`backend/config.py`（lifespan 配置覆写）
- `backend/core/errors.py`（WorkflowError 异常基类）
- `backend/deps.py`（run_agent_endpoint）、`backend/core/agent_sdk/registry.py`（运行队列与 RunHandle）、`backend/core/agent_sdk/events.py`（AgentEvent）、`backend/core/agent_sdk/direct.py`（sse_direct_response 直跑）
- `backend/core/agents/script_workflow.py`、`backend/core/agents/storyboard.py`（业务异常）
- `frontend/src/api/sse.ts` 及所有观流/直跑消费方（AgentRunDock、AgentRunProgress、useRunTask、RunTaskBanner、StepIdeationChat）

## 示例

✅ **正确做法:**

1. 普通 REST 响应返回 ApiResponse 同形 dict，业务数据放 `data`（参照 backend/deps.py 的 run_agent_endpoint；ApiResponse 模型当前无路由导入，按同形态返回 dict 即可）：
   ```python
   return {"success": True, "data": {"run_id": run_id}}
   ```
2. 业务失败直接 raise 继承 WorkflowError 的业务异常（ScriptWorkflowError / StoryboardError，可带 `status_code=...`，基类默认 400），交给 backend/main.py 的单个全局 WorkflowError handler 统一转 `{"detail": str(exc)}`，路由内不写 try/except、子类不自带 status_code 样板。
3. 资源不存在时 raise 带 detail 的 HTTPException（参照 backend/api/v1/agent_runs.py）：
   ```python
   raise HTTPException(404, detail=f"run 不存在或已过期: {run_id}")
   ```
4. 长任务一律 `get_run_registry().start(label, factory)`（或 backend/deps.py 的 `run_agent_endpoint`）立返 run_id；业务协程按 RunCoroFactory 签名经 `on_event` 发 AgentEvent、返回 dict 作 result_data；**run 可能排队**，前端进度感知依赖 queued/started 事件与 status 字段。
5. SSE 观流端点按固定序列输出：connected → AgentEvent.to_dict(seq)（`json.dumps ensure_ascii=False`，流中自然含 queued/started）→ done → [DONE]。
6. 前端消费 SSE 只用 `frontend/src/api/sse.ts` 的 fetchSSE；断线重连携带 `seq={lastSeq}` 增量续传并幂等去重（AgentRunProgress：最多 6 次 × 2s，connected 重置计数）。
7. 取消 run 走 `POST /api/v1/agent-runs/{run_id}/cancel`：排队中立即落终态（factory 不执行）；执行中由 `interrupt_event.set()` 让 agent 进程自然终止。

❌ **错误做法:**

1. 路由内自行 try/except 业务异常再手工拼错误 JSON —— 绕过全局 handler，错误体形态不再统一。
2. 长任务在 HTTP 请求内同步跑完再返回 —— 违背 run_id 立返与观流解耦（第 1 步 ideation 的 SSE 直跑是唯一例外形态，且自带断开取消）。
3. 前端用 EventSource 消费 SSE —— 不支持 POST，且自动重连会重复消费（fetchSSE 手写实现正为规避此点）。
4. 错误体不遵循 `{"detail": ...}` 形态 —— 前端 fetchSSE 只解析 `parsed.detail`。
5. 断线重连不带 seq 全量重放、或不做幂等去重。
6. 依赖 registry 跨进程重启恢复 run —— 注册表为进程内单例、无持久化。
7. 假定每 run 事件永不丢失 —— 事件 deque maxlen=5000，超限丢最旧。
8. 取消执行中的 run 时不经 `interrupt_event` 而采用其他终止方式 —— 约定是 `interrupt_event.set()` 后由 agent 进程自然终止。
9. 绕过 registry 排队、自行 `asyncio.create_task` 跑 agent —— 破坏 MAX_CONCURRENT_RUNS=5 并发上限与统一的 queued/started 事件、cancel 语义。
10. 假定 run 提交即执行、不做排队态处理 —— start 立返的 run 可能处于 queued，需消费 queued/started 事件（或轮询 status）。
11. 在新代码里引用已删除的 `start_agent_run`（deps 已改名 `run_agent_endpoint`）或 `output_format` 能力 —— 两者均已不存在。

## 迭代记录

| 日期 | 记录 |
|------|------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修订 — 核对 main.py/common.py/agent_runs.py/registry.py/events.py/deps.py/sse.ts/script_sessions.py/AgentRunProgress 后：修正 ApiResponse 采用现状（无路由导入、实际返回同形裸 dict）、fetchSSE onDone 触发时机（[DONE]/abort 不触发）；补全 status_code 定义位置、AgentEvent.to_dict/to_sse 细节、ideation 直跑 SSE 事件序列与断开取消语义；清空原 4 项待补充 |
| 2026-09-21 | 迭代修订 — 异常体系收口 WorkflowError 基类（新增 backend/core/errors.py，main.py 收敛为单个 handler，子类删 status_code 样板）；deps `start_agent_run` 改名 `run_agent_endpoint`；registry 新增 FIFO 排队机制（MAX_CONCURRENT_RUNS=5、_pending deque、5 个常驻 worker、RunHandle status 字段 queued→running→done、cancel 分叉、删除 task 字段）；events.py 新增 queued/started 类型与 queue_position 字段；`_sse_direct` 抽为 agent_sdk/direct.py 的 `sse_direct_response`（经 __init__.py 导出）；前端新增 AgentRunDock 全局任务坞（MainLayout 挂载、forceRender 保活 Modal）、agentRunStore、useRunTask（guardRunStart 等）、RunTaskBanner，AgentRunProgress 改为其弹窗内渲染器并支持排队态，AgentEvent 类型联合扩 queued/started |
