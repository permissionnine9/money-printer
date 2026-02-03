"""
工作流步骤相关的请求和响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from core.models.video_models import VideoParams, ScriptSegment, MaterialImage, SegmentFrame, GeneratedVideo


class Step1Request(BaseModel):
    """步骤1：提交脚本和参数"""
    script: str = Field(..., description="用户脚本")
    resolution: str = Field(default="1080p", description="分辨率")
    aspect_ratio: str = Field(default="16:9", description="宽高比")
    language: str = Field(default="zh-CN", description="语言")
    style: str = Field(default="cinematic", description="风格")
    camera_view: str = Field(default="third_person", description="视角")


class Step2Request(BaseModel):
    """步骤2：优化脚本"""
    extra_prompt: Optional[str] = Field(None, description="额外提示词，用于增加控制力（如：更多动作细节、特定风格、特殊要求等）")


class Step3Request(BaseModel):
    """步骤3：生成素材图"""
    extra_prompt: Optional[str] = Field(None, description="额外提示词，用于增加控制力（如：更鲜艳的颜色、卡通风格等）")
    reference_images: Optional[List[str]] = Field(None, description="参考图路径列表（上传的图片URL或本地路径），用于图生图模式")


class Step4Request(BaseModel):
    """步骤4：生成分片脚本"""
    extra_prompt: Optional[str] = Field(None, description="额外提示词，用于增加控制力（如：更多动作细节、特定镜头运动、时长控制等）")


class Step5Request(BaseModel):
    """步骤5：生成首尾帧"""
    pass


class Step6Request(BaseModel):
    """步骤6：生成视频"""
    pass


class StepResponse(BaseModel):
    """步骤响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
