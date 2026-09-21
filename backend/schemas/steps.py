"""
工作流步骤相关的请求和响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from backend.core.persistence.workspace_store import EPISODE_ID_PATTERN


class SelectEpisodeRequest(BaseModel):
    """步骤1：从剧本选集"""
    script_session_id: str = Field(..., description="剧本会话ID")
    episode_id: str = Field(..., pattern=EPISODE_ID_PATTERN, description="分集ID（如 ep_01）")
    resolution: str = Field(default="1080p", description="分辨率")
    aspect_ratio: str = Field(default="16:9", description="宽高比")
    film_style: str = Field(default="现实主义·照片级真人实拍与纪录片级质感", description="影视风格（如：现实主义·照片级真人实拍与纪录片级质感、二次元动漫·日式赛璐璐手绘与高饱和鲜艳色彩、3D动画·皮克斯式卡通渲染与电影级柔和光照、赛博朋克·霓虹光影与潮湿未来都市质感、国风水墨·写意留白与东方水墨氤氲意境、复古胶片·35mm胶片颗粒与暖调怀旧色彩）")
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


class SegmentReferenceImageIn(BaseModel):
    """步骤3：分镜参考图条目（保存时从素材源刷新 image_path）"""
    image_id: str = Field(..., description="素材池 ID（mat_* / lookbook_lb_*）")
    description: str = Field(default="", description="对图片描述（分镜侧独立编辑；为空时带出库内描述）")


class SegmentReferenceImagesUpdateRequest(BaseModel):
    """步骤3：保存分镜参考图（全量覆盖）"""
    reference_images: list[SegmentReferenceImageIn] = Field(default_factory=list, max_length=8, description="参考图列表")


class SegmentMaterialGenerateRequest(BaseModel):
    """步骤3：AI 生成分镜素材图"""
    user_prompt: str = Field(default="", description="用户自定义提示词（可含 @名称 引用文本）")
    mentioned_image_ids: list[str] = Field(default_factory=list, description="@ 引用的素材池图片 ID")
    reference_paths: list[str] = Field(default_factory=list, description="上传的自定义参考图路径（static/uploads/...）")
    model_config_id: Optional[str] = Field(None, description="生图模型配置ID（默认取默认生图模型）")


class SegmentCompleteRequest(BaseModel):
    """步骤3：完成/取消完成单个分镜的配置"""
    completed: bool = Field(default=True, description="True=完成当前分镜配置，False=取消完成")


class GenerateVideosRequest(BaseModel):
    """步骤4：生成视频（勾选分镜子集；缺省=全部已配置分镜）"""
    segment_indexes: Optional[list[int]] = Field(None, description="勾选参与生成的分镜 index 列表（须为已完成配置的分镜）")
    global_prompt: str = Field(default="", description="全局提示词（两段式导入时注入 timeline_data.globalPrompt，附加到整条时间轴）")


class StepResponse(BaseModel):
    """步骤响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
