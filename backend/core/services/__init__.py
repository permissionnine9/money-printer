"""服务模块"""
from .llm_service import LLMService
from .image_service import ImageService
from .video_service_jimeng import VideoService as VideoServiceJimeng
from .video_service_wan22 import VideoServiceWan22
from .video_service_doubao import VideoServiceDoubao

from backend.core.config import VIDEO_SERVICE_TYPE


def get_video_service():
    """根据配置获取视频服务实例

    Returns:
        VideoService 实例 (即梦、wan2.2 或 doubao)
    """
    if VIDEO_SERVICE_TYPE == "wan22":
        return VideoServiceWan22()
    elif VIDEO_SERVICE_TYPE == "doubao":
        return VideoServiceDoubao()
    else:
        return VideoServiceJimeng()


# 为了保持向后兼容，VideoService 作为别名指向当前配置的服务类
if VIDEO_SERVICE_TYPE == "wan22":
    VideoService = VideoServiceWan22
elif VIDEO_SERVICE_TYPE == "doubao":
    VideoService = VideoServiceDoubao
else:
    VideoService = VideoServiceJimeng


__all__ = [
    "LLMService",
    "ImageService",
    "VideoService",
    "VideoServiceJimeng",
    "VideoServiceWan22",
    "VideoServiceDoubao",
    "get_video_service",
]
