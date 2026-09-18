"""图片图库归档工具：生成的素材图按 static/images/{story_name}/{episode_name}/ 落盘

story_name 取剧本大纲根标题、episode_name 取分集标题（均需 sanitize）；
远程 URL 下载归档，本地临时文件移动归档；失败时由调用方回退用原始路径。
"""
import logging
import re
import shutil
from pathlib import Path

import httpx

from backend.core.utils.path_utils import IMAGE_SAVE_DIR, resolve_project_path

logger = logging.getLogger(__name__)

# 目录/文件名中的非法字符（路径分隔符 + Windows 保留字符 + 控制符）
_INVALID_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def sanitize_name(name: str, max_len: int = 50, fallback: str = "untitled") -> str:
    """净化为安全的目录/文件名片段：去非法字符、空白转下划线、限长、空值兜底"""
    cleaned = _INVALID_CHARS.sub("", (name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("._")
    return cleaned or fallback


def _guess_ext(source: str) -> str:
    """从 URL/路径后缀推断图片扩展名，默认 .png"""
    suffix = Path(source.split("?")[0]).suffix.lower()
    return suffix if suffix in (".png", ".jpg", ".jpeg", ".webp") else ".png"


async def archive_generated_image(
    source: str,
    story_name: str,
    episode_name: str,
    base_name: str,
    image_id: str,
) -> str:
    """把生成结果归档到图库目录 static/images/{story}/{episode}/，返回相对路径

    Args:
        source: 生图结果（远程 URL 或本地临时路径）
        story_name: 剧本名（目录段，sanitize）
        episode_name: 分集名（目录段，sanitize）
        base_name: 素材名（文件名主干，sanitize）
        image_id: 素材 ID（文件重名时的唯一后缀）

    Returns:
        归档后的相对路径（posix 风格）；下载/移动失败时返回原始 source（调用方兜底）
    """
    target_dir = IMAGE_SAVE_DIR / sanitize_name(story_name) / sanitize_name(episode_name)
    target_dir.mkdir(parents=True, exist_ok=True)

    ext = _guess_ext(source)
    stem = sanitize_name(base_name, max_len=40, fallback="material")
    target = target_dir / f"{stem}{ext}"
    if target.exists():  # 重名兜底：image_id 全局唯一
        target = target_dir / f"{stem}_{image_id}{ext}"

    try:
        if source.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(source)
                resp.raise_for_status()
                target.write_bytes(resp.content)
        else:
            local = resolve_project_path(source)
            if not local.exists():
                logger.warning(f"[图库归档] 源文件不存在，保留原始路径: {source}")
                return source
            shutil.move(str(local), target)
        rel = target.as_posix()
        logger.info(f"[图库归档] {image_id} → {rel}")
        return rel
    except Exception as e:
        logger.error(f"[图库归档] 失败（保留原始路径）: {e}")
        # 清理可能的半成品文件
        target.unlink(missing_ok=True)
        return source
