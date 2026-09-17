"""配置管理模块"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
BASE_DIR = Path(__file__).parent.parent

# 确保从项目根目录加载 .env 文件
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path, override=True)

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
# 可选值: "comfyui" (远程ComfyUI时间轴) 或 "jimeng" (即梦首尾帧) 或 "wan22" (阿里wan2.2首尾帧) 或 "doubao" (豆包-seedance-1.0-pro)
VIDEO_SERVICE_TYPE = os.getenv("VIDEO_SERVICE_TYPE", "comfyui")

# 远程 ComfyUI 服务配置
COMFYUI_BASE_URL = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
# 远程 ComfyUI 暂不可用时置为 true，用本地 mock 视频代替真实调用
COMFYUI_MOCK = os.getenv("COMFYUI_MOCK", "true").lower() in ("1", "true", "yes")
# ComfyUI API 格式工作流模板文件（MiniMaxH3TimelinePlanner 节点的 timeline_data 会被自动注入）
COMFYUI_WORKFLOW_PATH = BASE_DIR / "comfyui_workflow.json"
# ComfyUI 时间轴帧率（段时长/overlap 均以帧为单位换算）
COMFYUI_TIMELINE_FPS = 24

# 视频模型配置
SHENGSUANYUN_VIDEO_MODEL = "bytedance/jimeng_i2v_first_tail_v30"  # 即梦首尾帧模型
SHENGSUANYUN_VIDEO_MODEL_WAN22 = "ali/wan2.2-kf2v-flash"  # 阿里wan2.2首尾帧模型
SHENGSUANYUN_VIDEO_MODEL_DOUBAO = "bytedance/doubao-seedance-1.0-pro"  # 豆包-seedance-1.0-pro模型

# LLM模型配置
SHENGSUANYUN_LLM_MODEL = "bytedance/doubao-seed-1.8"  # 脚本优化、分片切割等

# 图片模型配置
SHENGSUANYUN_IMAGE_MODEL = "google/gemini-3-pro-image-preview"  # 素材图生成（文生图/图生图）
SHENGSUANYUN_FRAME_IMAGE_MODEL = "google/gemini-3-pro-image-preview"  # 首尾帧生成

SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP = 12  # 图生图请求间隔时间（秒）

# 阿里云 OSS 配置
OSS_ACCESS_KEY = os.getenv("OSS_ACCESS_KEY", "")
OSS_SECRET_KEY = os.getenv("OSS_SECRET_KEY", "")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "http://oss-cn-guangzhou.aliyuncs.com")
OSS_REGION = os.getenv("OSS_REGION", "cn-guangzhou")
OSS_BUCKET = os.getenv("OSS_BUCKET", "")


# 视频参数默认值
DEFAULT_VIDEO_PARAMS = {
    "resolution": "720p",
    "aspect_ratio": "16:9",
}

# 视频分辨率选项
RESOLUTION_OPTIONS = ["720p", "1080p", "4K"]

# 宽高比选项
ASPECT_RATIO_OPTIONS = ["16:9", "9:16", "1:1", "4:3"]
