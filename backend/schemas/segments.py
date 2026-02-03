"""
分片编辑相关的请求和响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional


class SegmentUpdateRequest(BaseModel):
    """更新分片脚本请求"""
    content: str = Field(..., description="分片内容")
    duration: float = Field(..., description="持续时间（秒）")
    action: Optional[str] = Field(None, description="动作描述")
    camera_movement: Optional[str] = Field(None, description="镜头运动")
    composition: Optional[str] = Field(None, description="构图")
    atmosphere: Optional[str] = Field(None, description="氛围")


class SegmentAddRequest(BaseModel):
    """添加分片脚本请求"""
    content: str = Field(..., description="分片内容")
    duration: float = Field(..., description="持续时间（秒）")
    action: Optional[str] = Field(None, description="动作描述")
    camera_movement: Optional[str] = Field(None, description="镜头运动")
    composition: Optional[str] = Field(None, description="构图")
    atmosphere: Optional[str] = Field(None, description="氛围")
    insert_after: int = Field(default=-1, description="插入位置（-1表示末尾）")


class SegmentDeleteRequest(BaseModel):
    """删除分片请求"""
    pass  # 通过路径参数指定索引


class SegmentResponse(BaseModel):
    """分片操作响应"""
    success: bool
    message: str
