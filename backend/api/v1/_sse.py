"""SSE 帧拼装工具（router 层共用，统一 ensure_ascii=False 与 [DONE] 哨兵）"""
import json


def sse_frame(obj) -> str:
    """对象 → 一帧 SSE data 行"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def sse_done() -> str:
    """流结束哨兵"""
    return "data: [DONE]\n\n"
