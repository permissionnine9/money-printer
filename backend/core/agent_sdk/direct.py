"""SSE 请求内直跑形态（不经 registry）

与 RunRegistry 观流形态互补：agent 在 SSE 响应内直接跑，事件经队列转流；
客户端断开触发 interrupt 优雅终止（5 秒宽限后强取消）。
"""
import asyncio
import json
import logging

from fastapi.responses import StreamingResponse

from backend.core.agent_sdk.events import AgentEvent

logger = logging.getLogger(__name__)


def sse_direct_response(coro_factory):
    """SSE 响应内直接跑 coro_factory(on_event, interrupt)，返回 StreamingResponse"""
    interrupt_holder: dict = {}

    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        FINAL = object()

        async def runner():
            interrupt = asyncio.Event()
            interrupt_holder["event"] = interrupt

            def on_event(ev: AgentEvent) -> None:
                queue.put_nowait(ev)

            try:
                data = await coro_factory(on_event, interrupt)
                await queue.put(("final", data))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("[剧本SSE] agent 运行异常")
                await queue.put(("final_err", str(e)))
            finally:
                await queue.put(FINAL)

        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is FINAL:
                    break
                if isinstance(item, AgentEvent):
                    yield item.to_sse(0)
                else:
                    kind, payload = item
                    if kind == "final":
                        yield f"data: {json.dumps({'type': 'final', 'data': payload}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'error', 'message': payload}, ensure_ascii=False)}\n\n"
        finally:
            # 客户端断开：先 interrupt（优雅终止），5 秒宽限后强取消
            event = interrupt_holder.get("event")
            if event and not task.done():
                event.set()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    task.cancel()
            elif not task.done():
                task.cancel()
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
