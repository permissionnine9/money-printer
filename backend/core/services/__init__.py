"""服务模块"""
from .llm_service import LLMService
from .image_service import ImageService
from .video_service import VideoService as VideoServiceJimeng
from .video_service_wan22 import VideoServiceWan22

from backend.core.config import VIDEO_SERVICE_TYPE


def get_video_service():
    """根据配置获取视频服务实例

    Returns:
        VideoService 实例 (即梦或 wan2.2)
    """
    if VIDEO_SERVICE_TYPE == "wan22":
        return VideoServiceWan22()
    else:
        return VideoServiceJimeng()


# 为了保持向后兼容，VideoService 作为别名指向当前配置的服务类
VideoService = VideoServiceWan22 if VIDEO_SERVICE_TYPE == "wan22" else VideoServiceJimeng


__all__ = [
    "LLMService",
    "ImageService",
    "VideoService",
    "VideoServiceJimeng",
    "VideoServiceWan22",
    "get_video_service",
]
