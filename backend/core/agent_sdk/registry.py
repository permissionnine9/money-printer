"""Agent 运行注册表：run 与 SSE 连接解耦

POST generate 立即返回 run_id，run 入 FIFO 队列（deque + 信号量唤醒）、由常驻
worker 协程消费（并发上限 max_concurrent，可运行时调整，超出排队）；入队发
queued 事件、领取执行发 started 事件；排队中 cancel **立即落终态**（不等
worker 领取），worker 领取时跳过已 done 的。前端连 GET runs/{run_id}/events
观流（缓冲回放 + 实时推送 + [DONE]）。关页面任务照跑，重开续看（带 seq 增量
续传）。
"""
import asyncio
import logging
import time
import uuid
from collections import deque
from typing import AsyncGenerator, Awaitable, Callable

from backend.core.agent_sdk.events import AgentEvent

logger = logging.getLogger(__name__)

MAX_EVENT_BUFFER = 5000        # 每 run 事件缓冲上限（text_delta 高频，超限丢弃最旧）
MAX_RUNS = 200                 # 注册表容量上限（超出时清理最早完成的 run）
DEFAULT_MAX_CONCURRENT_RUNS = 5  # 同时执行 run 的默认上限（可由外部经 set_max_concurrent 动态调整）


class RunHandle:
    """一个后台 agent run 的句柄"""

    def __init__(self, run_id: str, label: str):
        self.run_id = run_id
        self.label = label
        self.created_at = time.time()
        self.events: deque[tuple[int, AgentEvent]] = deque(maxlen=MAX_EVENT_BUFFER)
        self._seq = 0
        # 生命周期：queued（排队中）→ running（worker 已领取）→ done（终态）
        self.status = "queued"
        self.done = False
        self.success: bool | None = None
        self.error: str | None = None
        # 结构化终态原因（cancelled=用户主动取消），前端据此区分「已取消/失败」
        self.reason: str = ""
        # run 的业务层结果（如 {"message": ..., "data": ...}），POST 轮询兜底用
        self.result_data: dict = {}
        self.interrupt_event = asyncio.Event()
        self.cond = asyncio.Condition()

    def emit(self, event: AgentEvent) -> None:
        """记录事件并唤醒等待中的 SSE 流"""
        self._seq += 1
        self.events.append((self._seq, event))
        # notify 需持锁且需在事件循环内；若 emit 在无循环的线程上下文被调用则
        # 跳过唤醒（事件已入缓冲，观流在下一次 emit / 终态 notify 时追上——
        # 当前所有 on_event 调用点均在循环内，此分支仅为防御）
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._notify())

    async def _notify(self) -> None:
        async with self.cond:
            self.cond.notify_all()

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "label": self.label,
            "status": self.status,
            "done": self.done,
            "success": self.success,
            "error": self.error,
            "reason": self.reason,
            "result": self.result_data,
            "last_seq": self._seq,
        }


# 业务协程工厂：(on_event, interrupt_event) -> Awaitable[dict]
RunCoroFactory = Callable[[Callable[[AgentEvent], None], asyncio.Event], Awaitable[dict]]


class AgentRunRegistry:
    """全局 run 注册表（进程内单例）"""

    def __init__(self) -> None:
        self._runs: dict[str, RunHandle] = {}
        # 待执行队列用 deque 而非 asyncio.Queue：cancel 需对排队 run 即时落终态，
        # worker 领取时按 done 跳过（asyncio.Queue 无法移除中间元素）
        self._pending: deque[tuple[RunHandle, RunCoroFactory]] = deque()
        self._pending_signal = asyncio.Event()
        # 常驻 worker：task → 创建序号（持强引用防 GC；序号用于缩容时决定谁退出）
        self._workers: dict[asyncio.Task, int] = {}
        self._worker_seq = 0
        # 同时执行的 run 上限（外部经 set_max_concurrent 调整，如系统设置 API）
        self.max_concurrent = DEFAULT_MAX_CONCURRENT_RUNS

    @property
    def active_workers(self) -> int:
        """当前存活的 worker 数（未 done）"""
        return sum(1 for t in self._workers if not t.done())

    def set_max_concurrent(self, max_concurrent: int) -> None:
        """运行时调整并发上限：扩容立即补 worker，缩容由多余 worker 完成当前
        run 后自愿退出（执行中的任务不中断）"""
        self.max_concurrent = max_concurrent
        self._ensure_workers()
        # 唤醒空闲 worker：让它们重新走一遍缩容自检后自动 clear 信号
        self._pending_signal.set()
        logger.info(f"[AgentRun] 并发上限调整为 {max_concurrent}，当前 worker {self.active_workers} 个")

    def start(self, label: str, factory: RunCoroFactory) -> str:
        """提交一个 run 入队（FIFO，并发上限 max_concurrent），立即返回 run_id"""
        self._cleanup()
        run_id = uuid.uuid4().hex[:12]
        handle = RunHandle(run_id, label)
        self._runs[run_id] = handle
        self._ensure_workers()
        self._pending.append((handle, factory))
        self._pending_signal.set()
        handle.emit(AgentEvent(type="queued", queue_position=self._queue_position(handle)))
        logger.info(f"[AgentRun] 入队 {label} ({run_id})，待执行 {len(self._pending)} 个")
        return run_id

    def _queue_position(self, handle: RunHandle) -> int:
        """handle 前面待执行（未被取消）的任务数"""
        n = 0
        for h, _ in self._pending:
            if h is handle:
                break
            if not h.done:
                n += 1
        return n

    def _ensure_workers(self) -> None:
        """惰性启动常驻消费协程（首次提交时事件循环必然已就绪；启动失败不置位，下次提交重试）

        先剪枝已结束的 worker（CancelledError 逃逸等异常致死后 _workers 仍持强引用），
        再补足并发上限——否则死亡 worker 永不重建，并发能力静默下降。
        注：Event/Condition 惰性绑事件循环（Py3.10+），单 uvicorn 循环内安全。
        """
        self._workers = {t: seq for t, seq in self._workers.items() if not t.done()}
        while len(self._workers) < self.max_concurrent:
            task = asyncio.create_task(self._worker(self._worker_seq))
            self._workers[task] = self._worker_seq
            self._worker_seq += 1

    def _emit_queue_positions(self) -> None:
        """对剩余排队 run 重发 queued 事件（queue_position 前移），观流显示不冻结在过期数字"""
        position = 0
        for h, _ in self._pending:
            if h.done:
                continue
            h.emit(AgentEvent(type="queued", queue_position=position))
            position += 1

    async def _worker(self, seq: int) -> None:
        """常驻消费协程：按 FIFO 领取待执行 run（跳过排队期间已取消的）

        每轮领取前做缩容自检：按创建序号保留前 max_concurrent 个存活 worker，
        超出配额的自己（序号靠后）自愿退出——正在执行的 run 不受影响（检查点
        只在两次领取之间）。兜底捕获 _run 未覆盖的异常（如 notify 抛错），避免
        常驻 worker 被单次异常杀死；CancelledError 是 BaseException 自然穿透
        （进程关闭场景），死亡 worker 由 _ensure_workers 在下次提交时剪枝补齐。
        """
        while True:
            alive_seqs = sorted(s for t, s in self._workers.items() if not t.done())
            if seq not in alive_seqs[: self.max_concurrent]:
                logger.info(f"[AgentRun] worker#{seq} 超出并发配额 {self.max_concurrent}，自愿退出")
                return
            await self._pending_signal.wait()
            while self._pending:
                handle, factory = self._pending.popleft()
                if handle.done:
                    continue  # 排队期间已被 cancel 落终态，跳过
                self._emit_queue_positions()
                try:
                    await self._run(handle, factory)
                except Exception:  # noqa: BLE001 — 常驻 worker 不能因单次异常退出
                    logger.exception(f"[AgentRun] worker 执行 {handle.label} ({handle.run_id}) 异常")
                break
            else:
                self._pending_signal.clear()

    async def _run(self, handle: RunHandle, factory: RunCoroFactory) -> None:
        handle.status = "running"
        handle.emit(AgentEvent(type="started"))
        try:
            data = await factory(handle.emit, handle.interrupt_event)
            handle.result_data = data or {}
            handle.success = True
        except asyncio.CancelledError:
            handle.success = False
            handle.error = "已取消"
            handle.reason = "cancelled"
            raise
        except Exception as e:  # noqa: BLE001 — 后台任务需兜底，避免静默死掉
            logger.exception(f"[AgentRun] {handle.label} ({handle.run_id}) 异常")
            handle.success = False
            handle.error = str(e)
            handle.reason = getattr(e, "reason", "")
        finally:
            handle.status = "done"
            handle.done = True
            async with handle.cond:
                handle.cond.notify_all()

    def get(self, run_id: str) -> RunHandle | None:
        return self._runs.get(run_id)

    def cancel(self, run_id: str) -> bool:
        """取消 run：执行中触发 interrupt 由 agent 进程自然终止；
        排队中立即落终态（不等 worker 领取），观流立刻收尾"""
        handle = self._runs.get(run_id)
        if not handle or handle.done:
            return False
        if handle.status == "queued":
            handle.status = "done"
            handle.done = True
            handle.success = False
            handle.error = "已取消（排队中）"
            handle.reason = "cancelled"
            handle.emit(AgentEvent(type="error", message=handle.error, reason="cancelled"))
            self._emit_queue_positions()  # 取消排队项后，剩余排队项位置前移
            logger.info(f"[AgentRun] 排队取消 {handle.label} ({run_id})")
            return True
        handle.interrupt_event.set()
        logger.info(f"[AgentRun] 请求取消 {handle.label} ({run_id})")
        return True

    async def stream(self, run_id: str, from_seq: int = 0) -> AsyncGenerator[dict, None]:
        """按 seq 顺序流出一个 run 的事件（回放 + 实时），run 结束后停止"""
        handle = self._runs.get(run_id)
        if handle is None:
            raise KeyError(f"run 不存在: {run_id}")

        cursor = from_seq
        while True:
            async with handle.cond:
                pending = [(seq, ev) for seq, ev in handle.events if seq > cursor]
                if pending:
                    cursor = pending[-1][0]
                elif handle.done:
                    return
                else:
                    await handle.cond.wait()
                    continue
            for seq, ev in pending:
                yield ev.to_dict(seq)

    def _cleanup(self) -> None:
        """清理最早完成的 run，防止注册表无限增长"""
        if len(self._runs) <= MAX_RUNS:
            return
        done_runs = sorted(
            (h for h in self._runs.values() if h.done),
            key=lambda h: h.created_at,
        )
        for handle in done_runs[: len(self._runs) - MAX_RUNS]:
            self._runs.pop(handle.run_id, None)


# 进程内全局单例
_registry: AgentRunRegistry | None = None


def get_run_registry() -> AgentRunRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRunRegistry()
    return _registry
