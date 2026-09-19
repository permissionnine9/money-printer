---
name: Agent 异步运行框架
摘要: POST 立返 run_id + 后台 asyncio 任务 + 进程内注册表，SSE 缓冲回放/实时观流与取消，与业务解耦。
tags: backend, sse, asyncio, agent-sdk, registry
---

# Agent 异步运行框架

**状态:** 已完成
**最后更新:** 2026-09-19

## 功能概述

把"生成类"长任务（大纲/分集/定妆照/分镜素材/分镜提示词等 agent 调用）统一改造为异步运行模型：POST 立即返回 run_id，后台 asyncio.Task 执行，前端经 SSE 观流（缓冲回放 + 实时推送 + 断线 seq 续传），支持取消。关页面任务照跑，重开续看。

## 核心代码路径

- `backend/core/agent_sdk/registry.py` — AgentRunRegistry（进程内单例）+ RunHandle：事件缓冲、seq 递增、asyncio.Condition 驱动观流
- `backend/api/v1/agent_runs.py` — 通用 SSE 观流端点（GET /{run_id}/events、GET /{run_id} 轮询兜底、POST /{run_id}/cancel）
- `backend/deps.py` — `start_agent_run(label, factory)`（deps.py:90）：统一提交入口，返回 `{"success": True, "data": {"run_id": ...}}`
- `backend/core/agent_sdk/events.py` — AgentEvent 事件模型与 to_dict/to_sse 序列化

## 关键逻辑说明

1. **提交**：`AgentRunRegistry.start(label, factory)` 先 `_cleanup()`，生成 12 位 hex run_id，创建 RunHandle 并 `asyncio.create_task(_run(...))`，立即返回 run_id
2. **事件缓冲**：`RunHandle.events` 为 `deque(maxlen=MAX_EVENT_BUFFER=5000)`，每事件 `(seq, AgentEvent)`，seq 从 1 递增；text_delta 高频超限丢最旧（registry.py:18）
3. **容量控制**：`MAX_RUNS=200`，超限时按 created_at 清理最早**已完成**的 run（registry.py:138-147）
4. **观流**：`stream(run_id, from_seq)` 在 `asyncio.Condition` 上等待——有 seq > cursor 的积压先回放，run done 则结束，否则 `cond.wait()` 等新事件（registry.py:118-136）
5. **SSE 协议**（agent_runs.py:15-43）：先发 `connected`（含 label/last_seq）→ 回放+实时事件 → `done`（含 success/error/result 终态）→ `[DONE]` 哨兵；前端据 done 刷新 store
6. **异常兜底**：`_run` 中 CancelledError 置 success=False + re-raise；其他异常记录日志并置 error；finally 置 done 并 notify（registry.py:88-104）
7. **取消**：`cancel` 只 set `interrupt_event`，由 agent 进程（ClaudeSDKClient.interrupt）自然终止，不强杀 task
8. **调用方**：`backend/api/v1/script_sessions.py`（story_outline/episode_design/episode_redesign_*/lookbook_images/lookbook_regen_*）与 `backend/api/v1/steps.py`（storyboard_outline/segment_material_*/segment_prompt_*）共 9 处经 `start_agent_run` 提交

## 依赖与复用关系

- 依赖: `backend/core/agent_sdk/events.py`（AgentEvent）、asyncio 标准库
- 被依赖: `backend/api/v1/agent_runs.py`、`backend/deps.py:start_agent_run`、前端 `frontend/src/components/common/AgentRunProgress.tsx`
- 可复用组件: 任何需要"立返 + 观流"语义的后台任务均可经 registry.start 提交，与具体业务解耦

## 注意事项

- 注册表是**进程内内存单例**：多 worker 部署时 run 不可跨进程观流；重启即失
- `deque(maxlen=5000)` 截断后，断线重连的 from_seq 若小于缓冲内最旧 seq 会产生事件缺口——代码未处理该边界
- `emit` 在无事件循环的线程上下文调用时跳过 notify（靠消费侧轮询兜底，registry.py:44-50）
- run_id 不存在/过期返回 404（容量清理或重启后）

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
