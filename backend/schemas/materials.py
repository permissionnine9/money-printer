"""
素材图管理相关的请求和响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List


class MaterialEditRequest(BaseModel):
    """编辑素材图请求"""
    description: Optional[str] = Field(None, description="素材图描述")
    edit_prompt: Optional[str] = Field(None, description="编辑提示词（用于图生图）")
    image_path: Optional[str] = Field(None, description="新的图片路径")
    reference_images: Optional[List[str]] = Field(None, description="参考图路径列表")
    original_image_path: Optional[str] = Field(None, description="原始图片路径")


class MaterialRegenerateRequest(BaseModel):
    """重新生成素材图请求"""
    custom_prompt: Optional[str] = Field(None, description="自定义提示词（可选）")


class MaterialAddRequest(BaseModel):
    """新增素材图请求"""
    prompt: str = Field(..., description="生成提示词")
    description: Optional[str] = Field(None, description="素材图描述")
    reference_images: Optional[List[str]] = Field(None, description="参考图路径列表")


class MaterialResponse(BaseModel):
    """素材图操作响应"""
    success: bool
    message: str
    image_path: Optional[str] = None
    index: Optional[int] = None
