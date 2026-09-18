"""路径公共工具：保存目录常量与项目根路径解析（各服务共享，避免常量重复定义）"""
from pathlib import Path

# 视频保存目录（相对项目根 cwd，与 main.py 的 /static 挂载保持一致）
VIDEO_SAVE_DIR = Path("static/videos")

# 图片保存目录（同上）
IMAGE_SAVE_DIR = Path("static/images")

# 项目根目录（backend/ 的上一级）
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def resolve_project_path(path: str | Path) -> Path:
    """相对路径基于项目根解析，绝对路径原样返回"""
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path
