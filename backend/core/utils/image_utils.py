"""图片公共工具：压缩 / 字节读取 / Agent 缩略图（视频服务与生图服务共享）"""
import hashlib
import io
import logging
import mimetypes
import os
from pathlib import Path

import httpx
from PIL import Image

from backend.core.utils.path_utils import PROJECT_ROOT, resolve_project_path

logger = logging.getLogger(__name__)

# Agent 看图缩略图缓存目录（源图 > AGENT_THUMB_SOURCE_LIMIT 时才生成）
AGENT_THUMB_DIR = PROJECT_ROOT / "data" / "cache" / "agent_thumbs"
AGENT_THUMB_SOURCE_LIMIT = 512 * 1024  # 小于该字节数的源图直接用原图


def compress_image(image_data: bytes, max_size: int, quality: int) -> tuple[bytes, str]:
    """压缩图片到指定大小

    Args:
        image_data: 原始图片数据
        max_size: 最大边长（像素），超过则等比缩放
        quality: JPEG 压缩质量（1-100）

    Returns:
        (压缩后的图片数据, MIME类型)；失败时返回 (原始数据, "image/png")
    """
    try:
        image = Image.open(io.BytesIO(image_data))

        # 转换为 RGB 模式（JPEG 不支持 RGBA/调色板，透明区域铺白底）
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            if image.mode in ('RGBA', 'LA'):
                background.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
                image = background
            else:
                image = image.convert('RGB')
        elif image.mode != 'RGB':
            image = image.convert('RGB')

        # 计算缩放比例，保持宽高比
        width, height = image.size
        if max(width, height) > max_size:
            scale = max_size / max(width, height)
            image = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

        # 保存为 JPEG 并压缩
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=quality, optimize=True)
        output.seek(0)
        return output.read(), 'image/jpeg'

    except Exception as e:
        logger.error(f"图片压缩失败: {e}")
        # 压缩失败时返回原始数据
        return image_data, "image/png"

async def load_image_bytes(image_path: str, compress: bool = False, *, max_size: int = 1920, quality: int = 85) -> tuple[bytes | None, str | None]:
    """读取参考图为字节（支持本地路径与 URL），可选压缩

    Returns:
        (图片字节, MIME类型)，失败返回 (None, None)
    """
    try:
        if image_path.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(image_path)
                resp.raise_for_status()
                data = resp.content
        else:
            path = resolve_project_path(image_path)
            if not path.exists():
                logger.warning(f"参考图不存在: {path}")
                return None, None
            data = path.read_bytes()

        if compress:
            return compress_image(data, max_size, quality)
        return data, mimetypes.guess_type(image_path)[0] or "image/png"
    except Exception as e:
        logger.error(f"读取参考图失败 {image_path}: {e}")
        return None, None


def ensure_agent_thumbnail(image_path: str, max_size: int = 1024, quality: int = 80) -> str:
    """为 Agent Read 看图准备缩略图：大图压缩到 max_size 边长的 JPEG，小图/URL 原样返回

    Agent 读原图时 CLI 会把整图 base64 回显进 stream-json（SDK 默认 1MB 单条上限），
    高分辨率素材图会撑爆 buffer 且图片 token 昂贵；Agent 理解画面用缩略图足够。
    缓存于 data/cache/agent_thumbs/{stem}_{hash8}.jpg（hash 取源图大小+mtime，源图变化自动失效）；
    任何异常返回原路径兜底。
    """
    if image_path.startswith(("http://", "https://")):
        return image_path
    try:
        path = resolve_project_path(image_path)
        if not path.exists() or path.stat().st_size < AGENT_THUMB_SOURCE_LIMIT:
            return image_path

        thumb = AGENT_THUMB_DIR / (
            f"{path.stem}_{hashlib.md5(f'{path.stat().st_size}:{path.stat().st_mtime_ns}'.encode()).hexdigest()[:8]}.jpg"
        )
        if not thumb.exists():
            data, _ = compress_image(path.read_bytes(), max_size, quality)
            AGENT_THUMB_DIR.mkdir(parents=True, exist_ok=True)
            # 原子落盘：先写临时文件再 os.replace，进程中途被杀（如 uvicorn reload）
            # 只会残留 .tmp，不会留下截断的缩略图被缓存永久命中
            tmp = thumb.with_name(f"{thumb.stem}.{os.getpid()}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, thumb)
        return thumb.as_posix()
    except Exception as e:
        logger.warning(f"生成 Agent 缩略图失败（回退原图）{image_path}: {e}")
        return image_path
