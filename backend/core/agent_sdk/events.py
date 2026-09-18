"""Agent 事件类型定义与 SSE 序列化"""
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentEvent:
    """Agent 运行过程中的归一化事件

    type 取值：
    - thinking:   思考增量（delta）
    - text_delta: 文本增量（delta）
    - tool_use:   工具调用（id/tool/input）
    - tool_result: 工具结果（id/tool/result_preview）
    - result:     最终结果（text/session_id/usage）
    - error:      错误（message）
    """
    type: str
    delta: str = ""
    id: str = ""
    tool: str = ""
    input: dict = field(default_factory=dict)
    result_preview: str = ""
    text: str = ""
    session_id: str = ""
    usage: dict = field(default_factory=dict)
    message: str = ""

    def to_dict(self, seq: int | None = None) -> dict[str, Any]:
        """转为可 JSON 序列化的 dict（过滤空字段，减小 SSE 体积）"""
        data: dict[str, Any] = {"type": self.type}
        if seq is not None:
            data["seq"] = seq
        if self.delta:
            data["delta"] = self.delta
        if self.id:
            data["id"] = self.id
        if self.tool:
            data["tool"] = self.tool
        if self.input:
            data["input"] = self.input
        if self.result_preview:
            data["result_preview"] = self.result_preview
        if self.text:
            data["text"] = self.text
        if self.session_id:
            data["session_id"] = self.session_id
        if self.usage:
            data["usage"] = self.usage
        if self.message:
            data["message"] = self.message
        return data

    def to_sse(self, seq: int) -> str:
        """序列化为 SSE data 行"""
        return f"data: {json.dumps(self.to_dict(seq), ensure_ascii=False)}\n\n"
