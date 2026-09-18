"""
工作流步骤相关的请求和响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class SelectEpisodeRequest(BaseModel):
    """步骤1：从剧本选集"""
    script_session_id: str = Field(..., description="剧本会话ID")
    episode_id: str = Field(..., pattern=r"^ep_\d+$", description="分集ID（如 ep_01）")
    resolution: str = Field(default="1080p", description="分辨率")
    aspect_ratio: str = Field(default="16:9", description="宽高比")
    max_segment_duration: int = Field(default=15, ge=5, le=30, description="最大分片时长（秒），范围5-30秒。注意：当前即梦和wan2.2模型仅支持5秒或10秒视频生成，更长时长需要接入其他模型")


class StoryboardOutlineGenerateRequest(BaseModel):
    """步骤2：生成分镜大纲"""
    extra_prompt: Optional[str] = Field(None, description="额外提示词，用于增加控制力（如：节奏更紧凑、某个分镜拆分更细等）")


class StoryboardOutlineUpdateRequest(BaseModel):
    """步骤2：保存编辑后的分镜大纲导图"""
    mindmap: str = Field(..., description="markdown 层级大纲文本")


class SegmentConfigUpdateRequest(BaseModel):
    """步骤3：更新分镜配置（分镜形式 / overlap）"""
    mode: Optional[str] = Field(None, description="分镜形式: first_frame / last_frame / all_reference / first_last_frame")
    overlap: Optional[int] = Field(None, ge=0, le=3, description="与上一分镜的重叠秒数（0-3）")


class StepResponse(BaseModel):
    """步骤响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
