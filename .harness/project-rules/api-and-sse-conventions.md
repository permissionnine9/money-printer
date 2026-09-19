---
name: api-and-sse-conventions
摘要: 统一 ApiResponse 同形包络与 detail 错误体；业务异常经 backend/main.py 全局 handler 映射状态码；长任务 run_id 立返，SSE 按 seq 断线续传，前端 fetchSSE 手写解析。
tags: [API, SSE, 响应包络, 异常处理, agent-runs, fetchSSE]
---

# API 与 SSE 编码约定

**类别:** 实现规范
**最后更新:** 2026-09-19

## 原因

项目 API 层由三条既有实现主轴推导出本规范：**统一响应包络**、**集中式业务异常处理**、**长任务 run_id 立返与 SSE 观流解耦**。以下约定均直接来自当前源码实现，不做推测。

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

`backend/main.py:69-73` 用两个 `@app.exception_handler` 装饰**同一个** `business_error_handler`，覆盖：

| 业务异常 | 定义位置 | status_code |
|------|------|------|
| ScriptWorkflowError | backend/core/agents/script_workflow.py:45-50 | 构造参数 `status_code: int = 400`，挂实例属性 |
| StoryboardError | backend/core/agents/storyboard.py:44-49 | 同上 |

- 返回 `JSONResponse(status_code=getattr(exc, "status_code", 400), content={"detail": str(exc)})`：状态码由异常携带，缺省 400。业务代码 raise 时可显式指定（如 script_workflow.py:385 `raise ScriptWorkflowError(f"分集不存在: {episode_id}", status_code=404)`）。
- **路由层无需逐个 try/except**：直接 raise 业务异常即可。
- 其他错误沿用 FastAPI 惯用形态：`backend/api/v1/agent_runs.py` 对不存在的 run 直接 `raise HTTPException(404, detail=f"run 不存在或已过期: {run_id}")`，即错误体为 `{"detail": ...}`，前端 `fetchSSE` 解析 `parsed.detail`。

### 3. 应用骨架（backend/main.py）

| 项 | 约定 |
|------|------|
| CORS | `allow_origins=["http://localhost:5173", "http://localhost:3000"]`，`allow_credentials=True`，`allow_methods/headers=["*"]` |
| 静态资源 | `app.mount("/static", StaticFiles(directory="static"), name="static")` |
| 路由挂载 | 8 个子路由 prefix 均为 `/api/v1/*`：sessions / steps / uploads / assets / models / prompts / script_sessions / agent_runs |
| lifespan | 启动时调用 backend/config.py 的 `override_src_config()` 打印实际生效的模型配置 |

### 4. 长任务：run_id 立返与观流解耦

**启动侧（backend/deps.py:90-93）**：`get_run_registry().start(label, factory)` 立即返回，响应统一为 `{"success": True, "data": {"run_id": run_id}}`。

**registry（backend/core/agent_sdk/registry.py:78-86）** `AgentRunRegistry.start` 流程：`_cleanup()` → `run_id = uuid.uuid4().hex[:12]`（12 位 hex）→ `asyncio.create_task(self._run(...))` 后台执行 → 立即返回 run_id。

**RunCoroFactory 签名**：`Callable[[on_event: Callable[[AgentEvent], None], interrupt_event: asyncio.Event], Awaitable[dict]]` —— 业务协程经 `on_event` 回调发事件，返回的 dict 作为 `result_data`。

**后台执行 `_run` 语义**：

- 成功 → `result_data = data or {}`、`success=True`；
- `asyncio.CancelledError` → `success=False`、`error="已取消"` 后 re-raise；
- 其他异常 → `success=False`、`error=str(e)` 并 `logger.exception`；
- finally：`done=True` + `cond.notify_all()`。

**注册表与容量**：

- `get_run_registry()` 为进程内全局单例（模块级 `_registry`），`_runs: dict[run_id, RunHandle]`；**重启即失、无持久化**。
- `MAX_EVENT_BUFFER=5000`：每 run 事件 `deque(maxlen=5000)`，超限丢最旧。
- `MAX_RUNS=200`：超出时按 `created_at` 清理最早完成的 run（仅清 `done` 的）。

**RunHandle 字段**：`run_id, label, created_at, events: deque[(seq, AgentEvent)]（maxlen=5000）, _seq（从 0 起、emit 时自增）, done/success/error/result_data（结束后供轮询）, interrupt_event(asyncio.Event), task, cond(asyncio.Condition)`。

**emit**：`_seq+=1` → `events.append((seq, event))` → 若有运行中 loop 则 `create_task(_notify())`（`cond.notify_all`）；无 loop 时静默返回，由消费侧 `cond.wait` 轮询兜底。

### 5. SSE 观流协议（GET /api/v1/agent-runs/{run_id}/events?seq=N）

实现：`backend/api/v1/agent_runs.py:15-43`，`text/event-stream`（StreamingResponse）。事件序列固定为：

| 顺序 | 事件 | 说明 |
|------|------|------|
| 1 | `data: {"type":"connected","label":...,"last_seq":handle._seq}` | 连接即发 |
| 2 | `data: {AgentEvent.to_dict(seq)}` | 回放 + 实时事件（`json.dumps` `ensure_ascii=False`） |
| 3 | `data: {"type":"done","success":...,"error":...,"result":handle.result_data}` | 终态，前端据此刷新 store |
| 4 | `data: [DONE]` | 流结束哨兵 |

- **seq 语义**：查询参数 `seq: int = 0` 表示客户端已消费的最大事件序号；断线重连增量续传，默认 0 全量回放。`registry.stream(run_id, from_seq=seq)` 按 seq 顺序先回放缓冲中 `seq > cursor` 的事件，再实时等 cond。
- **错误**：run 不存在 → `HTTPException(404)`；流中 `KeyError` → 发 `{"type":"error","message":...}` 事件后**仍继续发 done + [DONE]**。
- **业务事件类型**：`AgentEvent`（backend/core/agent_sdk/events.py）`type: prompt / thinking / text_delta / tool_use / tool_result / result / error`。`to_dict(seq)` 从 `{"type": ...}` 起步：`seq` 非 None 时注入，其余字段（delta/id/tool/input/result_preview/text/session_id/usage/message/system_prompt/user_prompt/model）仅在非空时加入（过滤空字段减小 SSE 体积）；`to_sse(seq)` = `f"data: {json.dumps(self.to_dict(seq), ensure_ascii=False)}\n\n"`。

### 6. run 轮询兜底与取消

| 端点 | 行为 |
|------|------|
| `GET /api/v1/agent-runs/{run_id}` | 404 或 `{"success": True, "data": handle.to_dict()}`；`to_dict = {run_id, label, done, success, error, result, last_seq}` |
| `POST /api/v1/agent-runs/{run_id}/cancel` | `registry.cancel(run_id)`：handle 不存在或已 done 返回 False；否则 `interrupt_event.set()`，由 agent 进程**自然终止**；响应 `{"success": ok, "message": ...}` |

### 7. SSE 直跑形态（POST SSE，不经 registry）

- 端点：`POST /api/v1/script-sessions/{session_id}/ideation/message` 与 `.../ideation/finalize`（backend/api/v1/script_sessions.py:187-206），经 `_sse_direct`（同文件 L129-182）在 SSE 响应内直接跑 agent，**不经 registry、断开即取消**。
- 前端 `fetchSSE` 以 POST + JSON body 消费（EventSource 不支持 POST）。
- **直跑事件序列（已核对）**：`AgentEvent.to_sse(0)`（seq 恒 0，无 seq 续传语义；**无 connected/done 事件**）→ 终态 `data: {"type":"final","data":payload}` 或 `{"type":"error","message":...}` → `data: [DONE]`。
- **断开取消语义**：客户端断开时先 `interrupt_event.set()` 优雅终止，`asyncio.wait_for(asyncio.shield(task), timeout=5)` 给 5 秒宽限，超时才 `task.cancel()`。
- 前端消费方为 StepIdeationChat（frontend/src/components/script/StepIdeationChat.tsx）。

### 8. 前端 SSE 客户端（frontend/src/api/sse.ts）

`fetchSSE(url, body, handlers, signal)`：

- `body !== undefined` → POST + `Content-Type: application/json`；否则 GET。**不用 EventSource**（POST 不可用；GET 也用手写实现以避免自动重连重复消费）。
- 解析：`ReadableStream` `getReader` + `TextDecoder(stream: true)` 累积 buffer；按 `'\n\n'` 切分事件；每事件取以 `data:` 开头的行，`slice(5).trim()` 后 `join('\n')`；`data === "[DONE]"` 只置 doneReceived 不回调；其余 `JSON.parse` 后回调 `onEvent`，非 JSON 行忽略。
- handlers：`onEvent`（必选）/ `onError`（网络错误或非 2xx）/ `onDone`（**仅在读循环正常结束、即服务端关闭流后调用**；收到 [DONE] 哨兵本身不触发回调，AbortError 时直接 return 也不回调 onDone/onError）。
- 非 2xx：尝试 `JSON.parse` 响应体取 `parsed.detail` 作为错误 message，失败回退 `'HTTP {status}'`。
- abort：`AbortError` 视为主动取消直接 return，不算错误；调用方持 AbortController 取消。

**观流消费（AgentRunProgress 组件，frontend/src/components/script/AgentRunProgress.tsx）**：`GET /api/v1/agent-runs/{runId}/events?seq={lastSeq}` 观流；读流中断后重连最多 6 次（`MAX_RETRIES=6`）× 2s（`RETRY_INTERVAL=2000`），收到 connected 事件会将重试计数清零；seq 续传幂等去重（`ev.seq > lastSeq` 才推进，prompt 事件为赋值替换不累积）；`onError` 中 message 匹配 `/^HTTP/` 的 HTTP 层错误（如 run 404）直接失败不重连；可取消 run。

**前端 AgentEvent 类型**：`type: connected|prompt|thinking|text_delta|tool_use|tool_result|result|final|done|error`，字段含 `seq`、`delta/text`、`label/last_seq`、`system_prompt/user_prompt/model`、`data`（final）、`success/error/result`（done）（比后端 7 种业务事件类型更宽，含协议层 connected/done 与 final）。

## 适用范围

- `backend/api/v1/` 全部 8 个子路由（sessions / steps / uploads / assets / models / prompts / script_sessions / agent_runs）
- `backend/main.py`（全局异常处理与应用骨架）、`backend/schemas/common.py`（响应包络）、`backend/config.py`（lifespan 配置覆写）
- `backend/deps.py`、`backend/core/agent_sdk/registry.py`、`backend/core/agent_sdk/events.py`（run 注册表与事件）
- `backend/core/agents/script_workflow.py`、`backend/core/agents/storyboard.py`（业务异常）
- `frontend/src/api/sse.ts` 及所有观流/直跑消费方（AgentRunProgress、StepIdeationChat）

## 示例

✅ **正确做法:**

1. 普通 REST 响应返回 ApiResponse 同形 dict，业务数据放 `data`（参照 backend/deps.py:90-93；ApiResponse 模型当前无路由导入，按同形态返回 dict 即可）：
   ```python
   return {"success": True, "data": {"run_id": run_id}}
   ```
2. 业务失败直接 raise 已注册的业务异常（ScriptWorkflowError / StoryboardError，可带 `status_code=...`），交给 backend/main.py 的全局 business_error_handler 统一转 `{"detail": str(exc)}`，路由内不写 try/except。
3. 资源不存在时 raise 带 detail 的 HTTPException（参照 backend/api/v1/agent_runs.py）：
   ```python
   raise HTTPException(404, detail=f"run 不存在或已过期: {run_id}")
   ```
4. 长任务一律 `get_run_registry().start(label, factory)`（或 `backend/deps.py` 的 `start_agent_run`）立返 run_id；业务协程按 RunCoroFactory 签名经 `on_event` 发 AgentEvent、返回 dict 作 result_data。
5. SSE 观流端点按固定序列输出：connected → AgentEvent.to_dict(seq)（`json.dumps ensure_ascii=False`）→ done → [DONE]。
6. 前端消费 SSE 只用 `frontend/src/api/sse.ts` 的 fetchSSE；断线重连携带 `seq={lastSeq}` 增量续传并幂等去重（AgentRunProgress：最多 6 次 × 2s，connected 重置计数）。
7. 取消 run 走 `POST /api/v1/agent-runs/{run_id}/cancel`，由 `interrupt_event.set()` 让 agent 进程自然终止。

❌ **错误做法:**

1. 路由内自行 try/except 业务异常再手工拼错误 JSON —— 绕过全局 handler，错误体形态不再统一。
2. 长任务在 HTTP 请求内同步跑完再返回 —— 违背 run_id 立返与观流解耦（第 1 步 ideation 的 SSE 直跑是唯一例外形态，且自带断开取消）。
3. 前端用 EventSource 消费 SSE —— 不支持 POST，且自动重连会重复消费（fetchSSE 手写实现正为规避此点）。
4. 错误体不遵循 `{"detail": ...}` 形态 —— 前端 fetchSSE 只解析 `parsed.detail`。
5. 断线重连不带 seq 全量重放、或不做幂等去重。
6. 依赖 registry 跨进程重启恢复 run —— 注册表为进程内单例、无持久化。
7. 假定每 run 事件永不丢失 —— 事件 deque maxlen=5000，超限丢最旧。
8. 取消 run 时不经 `interrupt_event` 而采用其他终止方式 —— 约定是 `interrupt_event.set()` 后由 agent 进程自然终止。

## 迭代记录

| 日期 | 记录 |
|------|------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修订 — 核对 main.py/common.py/agent_runs.py/registry.py/events.py/deps.py/sse.ts/script_sessions.py/AgentRunProgress 后：修正 ApiResponse 采用现状（无路由导入、实际返回同形裸 dict）、fetchSSE onDone 触发时机（[DONE]/abort 不触发）；补全 status_code 定义位置、AgentEvent.to_dict/to_sse 细节、ideation 直跑 SSE 事件序列与断开取消语义；清空原 4 项待补充 |
