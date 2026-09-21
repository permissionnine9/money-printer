"""Agent run 通用端点：SSE 观流（缓冲回放 + 实时）与取消

与具体业务（剧本/视频）解耦：任何经 AgentRunRegistry 启动的后台 run 都从这里观流。
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.v1._sse import sse_done, sse_frame
from backend.core.agent_sdk import RunHandle, get_run_registry

router = APIRouter()


def _load_run(run_id: str) -> RunHandle:
    """加载 run 句柄，不存在抛 404"""
    handle = get_run_registry().get(run_id)
    if handle is None:
        raise HTTPException(status_code=404, detail=f"run 不存在或已过期: {run_id}")
    return handle


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, seq: int = 0):
    """SSE 观流：先回放 seq 之后的缓冲事件，再实时推送；run 结束后发 [DONE]

    Args:
        seq: 客户端已消费的最大事件序号（断线重连增量续传，默认 0 全量回放）
    """
    registry = get_run_registry()
    handle = _load_run(run_id)

    async def gen():
        yield sse_frame({"type": "connected", "label": handle.label, "last_seq": handle._seq})
        try:
            async for event in registry.stream(run_id, from_seq=seq):
                yield sse_frame(event)
        except KeyError as e:
            yield sse_frame({"type": "error", "message": str(e)})
        # 结束哨兵：附带 run 终态，前端据此刷新 store（reason=cancelled 区分用户主动取消）
        yield sse_frame({
            "type": "done",
            "success": handle.success,
            "error": handle.error,
            "reason": handle.reason,
            "result": handle.result_data,
        })
        yield sse_done()

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str):
    """取消 agent run（触发 interrupt，由 agent 进程自然终止）"""
    ok = get_run_registry().cancel(run_id)
    return {"success": ok, "message": "已请求取消" if ok else "run 不存在或已结束"}
