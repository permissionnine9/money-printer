"""
工作流步骤相关的请求和响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class Step1Request(BaseModel):
    """步骤1：提交脚本和参数"""
    script: str = Field(..., description="用户脚本")
    resolution: str = Field(default="1080p", description="分辨率")
    aspect_ratio: str = Field(default="16:9", description="宽高比")
    max_segment_duration: int = Field(default=15, ge=5, le=30, description="最大分片时长（秒），范围5-30秒。注意：当前即梦和wan2.2模型仅支持5秒或10秒视频生成，更长时长需要接入其他模型")


class Step2Request(BaseModel):
    """步骤2：优化脚本"""
    extra_prompt: Optional[str] = Field(None, description="额外提示词，用于增加控制力（如：更多动作细节、特定风格、特殊要求等）")
    use_original: Optional[bool] = Field(None, description="直接采用第一步原始脚本，跳过 LLM 优化")


class Step3Request(BaseModel):
    """步骤3：生成思维导图"""
    extra_prompt: Optional[str] = Field(None, description="额外提示词，用于增加控制力")


class Step4Request(BaseModel):
    """步骤4：生成素材图"""
    extra_prompt: Optional[str] = Field(None, description="额外提示词，用于增加控制力（如：更鲜艳的颜色、卡通风格等）")
    reference_images: Optional[List[str]] = Field(None, description="参考图路径列表（上传的图片URL或本地路径），用于图生图模式")
    model_config_id: Optional[str] = Field(None, description="生图模型配置ID（模型管理中添加），不传则使用系统默认配置")


class MindmapUpdateRequest(BaseModel):
    """思维导图人工编辑保存"""
    mindmap: str = Field(..., description="思维导图 markdown 内容")


class OverlapUpdateRequest(BaseModel):
    """相邻分片 overlap 参数更新"""
    overlap_seconds: float = Field(..., description="相邻分片重叠时长（秒），0-5", ge=0, le=5)


class Step5Request(BaseModel):
    """步骤5：生成分片脚本"""
    extra_prompt: Optional[str] = Field(None, description="额外提示词，用于增加控制力（如：更多动作细节、特定镜头运动、时长控制等）")


class OptimizeSegmentPromptRequest(BaseModel):
    """优化分片提示词请求"""
    custom_requirement: Optional[str] = Field(None, description="用户自定义要求，用于指导 LLM 如何优化提示词")


class StepResponse(BaseModel):
    """步骤响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
