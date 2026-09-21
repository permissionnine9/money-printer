---
name: Agent 异步运行框架
摘要: POST 立返 run_id + FIFO 排队（并发上限 5）+ 进程内注册表，queued/started 事件可观测，SSE 缓冲回放/实时观流与取消，前端全局任务坞（AgentRunDock）消费，与业务解耦。
tags: backend, sse, asyncio, agent-sdk, registry, queue
---

# Agent 异步运行框架

**状态:** 已完成
**最后更新:** 2026-09-21

## 功能概述

把"生成类"长任务（大纲/分集/核心素材图/分镜素材/分镜提示词等 agent 调用）统一改造为异步运行模型：POST 立即返回 run_id，后台按 FIFO 排队执行（并发上限 5），前端经 SSE 观流（缓冲回放 + 实时推送 + 断线 seq 续传），支持取消（排队中即时取消 / 执行中 interrupt 优雅终止）。关页面任务照跑，重开续看；前端经全局任务坞（AgentRunDock，挂 MainLayout）跨页面观察任务进度。

## 核心代码路径

- `backend/core/agent_sdk/registry.py` — AgentRunRegistry（进程内单例）+ RunHandle：FIFO 排队（`MAX_CONCURRENT_RUNS=5`，registry.py:22）、5 个常驻 worker 协程、事件缓冲、seq 递增、asyncio.Condition 驱动观流、run `status`（queued→running→done）
- `backend/api/v1/agent_runs.py` — 通用 SSE 观流端点（GET /{run_id}/events、GET /{run_id} 轮询兜底、POST /{run_id}/cancel）
- `backend/deps.py` — `run_agent_endpoint(label, factory)`（原 `start_agent_run` 改名，签名不变）：统一提交入口，返回 `{"success": True, "data": {"run_id": ...}}`
- `backend/core/agent_sdk/events.py` — AgentEvent 事件模型与 to_dict/to_sse 序列化；type 含 `queued`（带 queue_position）/`started`
- `backend/core/agent_sdk/direct.py` — `sse_direct_response(coro_factory)`：SSE 请求内直跑编排（不经 registry），自 script_sessions.py 的 `_sse_direct` 抽出，router 只留 HTTP 包装
- `backend/core/agent_sdk/wrapper.py` — run_agent 底层；`MAX_STREAM_BUFFER_SIZE=16MB`（防 Agent Read 图片 base64 撑爆 SDK 默认 1MB 缓冲）；已删除 output_format 结构化输出
- `frontend/src/stores/agentRunStore.ts` + `frontend/src/components/layout/AgentRunDock.tsx` — 全局任务坞（zustand runs 队列 + Dock 弹窗消费）
- `tests/manual/test_agent_run_queue.py` — 队列语义回归（纯 asyncio 无 LLM）

## 关键逻辑说明

1. **提交与排队**：`AgentRunRegistry.start(label, factory)` 先 `_cleanup()`，生成 12 位 hex run_id，创建 RunHandle 后**不直接 create_task**，而是 append 进 `_pending` deque（保留 cancel 即时落终态的能力），emit `AgentEvent(type="queued", queue_position=N)`，立即返回 run_id
2. **并发执行**：`_ensure_workers()`（registry.py:112-117）惰性启动 5 个常驻 `_worker()` 协程（持强引用防 GC），按 FIFO popleft（跳过排队期间已取消的）；`_run` 领取时置 `status="running"` 并 emit `started` 事件，finally 落 `status="done"`
3. **事件缓冲**：`RunHandle.events` 为 `deque(maxlen=MAX_EVENT_BUFFER=5000)`，每事件 `(seq, AgentEvent)`，seq 从 1 递增；text_delta 高频超限丢最旧
4. **容量控制**：`MAX_RUNS=200`，超限时按 created_at 清理最早**已完成**的 run
5. **观流**：`stream(run_id, from_seq)` 在 `asyncio.Condition` 上等待——有 seq > cursor 的积压先回放，run done 则结束，否则 `cond.wait()` 等新事件
6. **SSE 协议**（agent_runs.py）：先发 `connected`（含 label/last_seq）→ 回放+实时事件（自然含 queued/started）→ `done`（含 success/error/result 终态）→ `[DONE]` 哨兵；前端据 done 刷新 store
7. **异常兜底**：`_run` 中 CancelledError 置 success=False + re-raise；其他异常记录日志并置 error；finally 置 done 并 notify
8. **取消分叉**：排队中 cancel → 立即落终态（done/success=False/error="已取消（排队中）"）+ emit error 事件，factory 不执行；执行中 cancel → 仍只 set `interrupt_event`，由 agent 进程（ClaudeSDKClient.interrupt）自然终止，不强杀 task
9. **RunHandle 演进**：新增 `status` 字段（to_dict 输出）；删除 `task` 字段
10. **调用方**：`backend/api/v1/script_sessions.py`（outline/episodes/lookbook 等）与 `backend/api/v1/steps.py`（storyboard_outline/segment_material_*/segment_prompt_*）经 `run_agent_endpoint` 提交
11. **前端消费**：agentRunStore（runs: AgentRunTask[]，kind 四类 segment_prompt/outline/episodes/storyboard_outline，status queued/running/success/error）+ AgentRunDock（每 run 一个 forceRender 保活 Modal 内嵌 AgentRunProgress，收起不卸载 SSE 不断流；成功按 kind 提示并 removeRun，失败标红留列）+ RunTaskBanner + useRunTask（guardRunStart 防重复入队）

## 依赖与复用关系

- 依赖: `backend/core/agent_sdk/events.py`（AgentEvent）、asyncio 标准库
- 被依赖: `backend/api/v1/agent_runs.py`、`backend/deps.py:run_agent_endpoint`、前端 `frontend/src/components/layout/AgentRunDock.tsx`（内嵌 `frontend/src/components/script/AgentRunProgress.tsx`）
- 可复用组件: 任何需要"立返 + 观流"语义的后台任务均可经 registry.start 提交，与具体业务解耦；SSE 直跑形态用 `direct.py` 的 `sse_direct_response`

## 注意事项

- 注册表是**进程内内存单例**：多 worker 部署时 run 不可跨进程观流；重启即失（排队中的 run 亦然）
- 并发上限 5：第 6 个及以后的提交会排队，POST 立返 run_id 但不一定立即执行（前端有「排队中（前面还有 N 个任务）」文案）
- `deque(maxlen=5000)` 截断后，断线重连的 from_seq 若小于缓冲内最旧 seq 会产生事件缺口——代码未处理该边界
- `emit` 在无事件循环的线程上下文调用时跳过 notify（靠消费侧轮询兜底）
- run_id 不存在/过期返回 404（容量清理或重启后）
- `run_agent` 已无 output_format/structured_output；结构化产出由 prompt 约束 + 调用方解析（AgentStepService.run 的 parse 回调）承担

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-21 | 同步重构 — registry 引入 FIFO 排队（MAX_CONCURRENT_RUNS=5 + 常驻 worker + queued/started 事件 + status 生命周期 + 排队即时取消）；start_agent_run 改名 run_agent_endpoint；_sse_direct 抽为 agent_sdk/direct.py；wrapper 删 output_format、增 MAX_STREAM_BUFFER_SIZE=16MB；新增前端全局任务坞（agentRunStore/AgentRunDock/RunTaskBanner/useRunTask）；新增 test_agent_run_queue.py |
