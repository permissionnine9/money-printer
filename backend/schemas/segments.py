"""
分片编辑相关的请求和响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List


class SegmentUpdateRequest(BaseModel):
    """更新分片脚本请求"""
    content: str = Field(..., description="分片内容")
    duration: float = Field(..., description="持续时间（秒）")
    action: Optional[str] = Field(None, description="动作描述")
    camera_movement: Optional[str] = Field(None, description="镜头运动")
    composition: Optional[str] = Field(None, description="构图")
    atmosphere: Optional[str] = Field(None, description="氛围")
    video_generation_mode: Optional[str] = Field(None, description="视频生成模式：first_last_frame 或 first_frame_reference")
    first_frame_mode: Optional[str] = Field(None, description="首帧模式：generate、reuse_prev、use_video_snapshot 等")


class SegmentAddRequest(BaseModel):
    """添加分片脚本请求"""
    content: str = Field(..., description="分片内容")
    duration: float = Field(..., description="持续时间（秒）")
    action: Optional[str] = Field(None, description="动作描述")
    camera_movement: Optional[str] = Field(None, description="镜头运动")
    composition: Optional[str] = Field(None, description="构图")
    atmosphere: Optional[str] = Field(None, description="氛围")
    insert_after: int = Field(default=-1, description="插入位置（-1表示末尾）")


class SegmentBatchRegenerateRequest(BaseModel):
    """批量重新生成分片请求"""
    segment_indices: List[int] = Field(..., description="要重新生成的分片索引列表")
    extra_prompt: Optional[str] = Field(None, description="额外的自定义提示词")


class SegmentResponse(BaseModel):
    """分片操作响应"""
    success: bool
    message: str
