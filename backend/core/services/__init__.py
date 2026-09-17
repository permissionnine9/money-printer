"""服务模块"""
from .llm_service import LLMService
from .image_service import ImageService
from .comfyui_service import VideoServiceComfyUI, ComfyUIClient, TimelineBuilder
from .video_service_jimeng import VideoService as VideoServiceJimeng
from .video_service_wan22 import VideoServiceWan22
from .video_service_doubao import VideoServiceDoubao

from backend.core.config import VIDEO_SERVICE_TYPE


def get_video_service():
    """根据配置获取视频服务实例

    Returns:
        VideoService 实例 (comfyui、即梦、wan2.2 或 doubao)
    """
    if VIDEO_SERVICE_TYPE == "comfyui":
        return VideoServiceComfyUI()
    elif VIDEO_SERVICE_TYPE == "wan22":
        return VideoServiceWan22()
    elif VIDEO_SERVICE_TYPE == "doubao":
        return VideoServiceDoubao()
    else:
        return VideoServiceJimeng()


# 为了保持向后兼容，VideoService 作为别名指向当前配置的服务类
if VIDEO_SERVICE_TYPE == "comfyui":
    VideoService = VideoServiceComfyUI
elif VIDEO_SERVICE_TYPE == "wan22":
    VideoService = VideoServiceWan22
elif VIDEO_SERVICE_TYPE == "doubao":
    VideoService = VideoServiceDoubao
else:
    VideoService = VideoServiceJimeng


def get_legacy_video_service():
    """获取逐分片视频服务（具备 generate_video_from_frames 接口的实现）

    ComfyUI 走整段时间轴生成，不支持单分片接口；配置为 comfyui 时
    legacy 接口回退到 doubao。
    """
    if VIDEO_SERVICE_TYPE in ("wan22", "doubao"):
        return get_video_service()
    if VIDEO_SERVICE_TYPE == "jimeng":
        return VideoServiceJimeng()
    return VideoServiceDoubao()


__all__ = [
    "LLMService",
    "ImageService",
    "VideoService",
    "VideoServiceComfyUI",
    "ComfyUIClient",
    "TimelineBuilder",
    "VideoServiceJimeng",
    "VideoServiceWan22",
    "VideoServiceDoubao",
    "get_video_service",
]
