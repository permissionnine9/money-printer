"""
首尾帧管理相关的请求和响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional


class FrameRegenerateRequest(BaseModel):
    """重新生成首尾帧请求"""
    frame_type: str = Field(..., description="帧类型：first 或 last")
    custom_prompt: Optional[str] = Field(None, description="自定义提示词（可选）")


class FrameUploadRequest(BaseModel):
    """上传首尾帧请求"""
    frame_type: str = Field(..., description="帧类型：first 或 last")
    image_path: str = Field(..., description="上传的图片路径")


class FrameReuseRequest(BaseModel):
    """复用帧请求"""
    frame_type: str = Field(..., description="帧类型：first 或 last")


class FrameResponse(BaseModel):
    """首尾帧操作响应"""
    success: bool
    message: str
    frame_path: Optional[str] = None
