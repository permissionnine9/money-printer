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

# 文件化创作工作区（剧本/分镜 markdown 产物的权威存储，位于项目根）
WORKSPACE_DIR = Path(__file__).parent.parent.parent / "workspace"

# 确保目录存在
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

# 视频生成服务：远程 ComfyUI 时间轴（唯一链路）
COMFYUI_BASE_URL = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
# 远程 ComfyUI 暂不可用时置为 true，用本地 mock 视频代替真实调用
COMFYUI_MOCK = os.getenv("COMFYUI_MOCK", "true").lower() in ("1", "true", "yes")
# ComfyUI API 格式工作流模板文件（MiniMaxH3TimelinePlanner 节点的 timeline_data 会被自动注入）
COMFYUI_WORKFLOW_PATH = BASE_DIR / "comfyui_workflow.json"
# ComfyUI 时间轴帧率（段时长/overlap 均以帧为单位换算）
COMFYUI_TIMELINE_FPS = 24

# 生图模型由「模型管理」配置决定，不再内置默认模型；未配置时生图功能显式报错

IMAGE_REQUEST_TIME_GAP = 12  # 多张图片连续提交的间隔时间（秒，避免生图服务限流）

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
