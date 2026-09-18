"""Agent 运行注册表：run 与 SSE 连接解耦

POST generate 立即返回 run_id，后台 asyncio.Task 执行；
前端连 GET runs/{run_id}/events 观流（缓冲回放 + 实时推送 + [DONE]）。
关页面任务照跑，重开续看（带 seq 增量续传）。
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


class RunHandle:
    """一个后台 agent run 的句柄"""

    def __init__(self, run_id: str, label: str):
        self.run_id = run_id
        self.label = label
        self.created_at = time.time()
        self.events: deque[tuple[int, AgentEvent]] = deque(maxlen=MAX_EVENT_BUFFER)
        self._seq = 0
        self.done = False
        self.success: bool | None = None
        self.error: str | None = None
        # run 的业务层结果（如 {"message": ..., "data": ...}），POST 轮询兜底用
        self.result_data: dict = {}
        self.interrupt_event = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.cond = asyncio.Condition()

    def emit(self, event: AgentEvent) -> None:
        """记录事件并唤醒等待中的 SSE 流"""
        self._seq += 1
        self.events.append((self._seq, event))
        # notify 需要 hold lock；emit 可能在无循环的线程上下文被调用——
        # 这里统一走同步安全路径（未持锁时 notify 由消费侧轮询兜底）
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
            "done": self.done,
            "success": self.success,
            "error": self.error,
            "result": self.result_data,
            "last_seq": self._seq,
        }


# 业务协程工厂：(on_event, interrupt_event) -> Awaitable[dict]
RunCoroFactory = Callable[[Callable[[AgentEvent], None], asyncio.Event], Awaitable[dict]]


class AgentRunRegistry:
    """全局 run 注册表（进程内单例）"""

    def __init__(self) -> None:
        self._runs: dict[str, RunHandle] = {}

    def start(self, label: str, factory: RunCoroFactory) -> str:
        """启动一个后台 run，立即返回 run_id"""
        self._cleanup()
        run_id = uuid.uuid4().hex[:12]
        handle = RunHandle(run_id, label)
        self._runs[run_id] = handle
        handle.task = asyncio.create_task(self._run(handle, factory))
        logger.info(f"[AgentRun] 启动 {label} ({run_id})")
        return run_id

    async def _run(self, handle: RunHandle, factory: RunCoroFactory) -> None:
        try:
            data = await factory(handle.emit, handle.interrupt_event)
            handle.result_data = data or {}
            handle.success = True
        except asyncio.CancelledError:
            handle.success = False
            handle.error = "已取消"
            raise
        except Exception as e:  # noqa: BLE001 — 后台任务需兜底，避免静默死掉
            logger.exception(f"[AgentRun] {handle.label} ({handle.run_id}) 异常")
            handle.success = False
            handle.error = str(e)
        finally:
            handle.done = True
            async with handle.cond:
                handle.cond.notify_all()

    def get(self, run_id: str) -> RunHandle | None:
        return self._runs.get(run_id)

    def cancel(self, run_id: str) -> bool:
        """取消 run（触发 interrupt，由 agent 进程自然终止）"""
        handle = self._runs.get(run_id)
        if not handle or handle.done:
            return False
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
