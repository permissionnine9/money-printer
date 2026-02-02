"""配置管理模块"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# 项目根目录
BASE_DIR = Path(__file__).parent.parent

# 静态文件目录
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"
VIDEOS_DIR = STATIC_DIR / "videos"

# 确保目录存在
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# 胜算云 API 配置（用于视频生成和图片生成）
SHENGSUANYUN_API_KEY = os.getenv(
    "SHENGSUANYUN_API_KEY",
    "OmlJTjwvW5xt-xcnopFpD6jnHF5uVK9Tyi0ac9TNfl8geCxZeW73q16sw8Zpce8wcgks8niZoRNv-w"
)
SHENGSUANYUN_BASE_URL = "https://router.shengsuanyun.com/api/v1"

# 视频生成服务配置
# 可选值: "jimeng" (即梦首尾帧) 或 "wan22" (阿里wan2.2首尾帧)
VIDEO_SERVICE_TYPE = os.getenv("VIDEO_SERVICE_TYPE", "wan22")

# 视频模型配置
SHENGSUANYUN_VIDEO_MODEL = "bytedance/jimeng_i2v_first_tail_v30"  # 即梦首尾帧模型
SHENGSUANYUN_VIDEO_MODEL_WAN22 = "ali/wan2.2-kf2v-flash"  # 阿里wan2.2首尾帧模型

# 图片模型配置
SHENGSUANYUN_IMAGE_MODEL = "openai/gpt-image-1.5"  # 文生图模型
SHENGSUANYUN_IMAGE2IMAGE_MODEL = "google/gemini-2.5-flash-image"  # 图生图模型（支持参考图）
SHENGSUANYUN_MATERIAL_IMAGE_MODEL = "google/gemini-3-pro-image-preview"  # 素材图模型（支持图生图，高质量）

SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP = 4  # 图生图请求间隔时间（秒）

# 阿里云 OSS 配置
OSS_ACCESS_KEY = os.getenv("OSS_ACCESS_KEY", "")
OSS_SECRET_KEY = os.getenv("OSS_SECRET_KEY", "")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "http://oss-cn-guangzhou.aliyuncs.com")
OSS_REGION = os.getenv("OSS_REGION", "cn-guangzhou")
OSS_BUCKET = os.getenv("OSS_BUCKET", "")


# 视频参数默认值
DEFAULT_VIDEO_PARAMS = {
    "resolution": "1080p",
    "aspect_ratio": "16:9",
    "language": "zh-CN",
    "style": "cinematic",
    "perspective": "third_person",
}

# 视频分辨率选项
RESOLUTION_OPTIONS = ["720p", "1080p", "4K"]

# 宽高比选项
ASPECT_RATIO_OPTIONS = ["16:9", "9:16", "1:1", "4:3"]

# 语言选项
LANGUAGE_OPTIONS = ["zh-CN", "en-US", "ja-JP", "ko-KR"]

# 美学风格选项
STYLE_OPTIONS = [
    "cinematic",      # 电影风格
    "anime",          # 动漫风格
    "realistic",      # 写实风格
    "cartoon",        # 卡通风格
    "watercolor",     # 水彩风格
    "oil_painting",   # 油画风格
    "pixel_art",      # 像素风格
    "3d_render",      # 3D渲染风格
]

# 视角选项
PERSPECTIVE_OPTIONS = [
    "first_person",   # 第一人称
    "third_person",   # 第三人称
    "aerial",         # 航拍视角
    "close_up",       # 特写
    "wide_angle",     # 广角
]

# 每个分片的最大时长（秒）
MAX_SEGMENT_DURATION = 8
