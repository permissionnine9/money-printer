"""
Backend 配置文件

注意：core 已统一使用 gemini-3-pro-image-preview 模型，无需额外配置覆盖
"""
import logging

logger = logging.getLogger(__name__)


def override_src_config():
    """
    配置检查函数（保留用于向后兼容）

    注意：core 已统一使用 gemini-3-pro-image-preview，无需覆盖配置
    """
    logger.info("所有图片生成已统一使用 gemini-3-pro-image-preview 模型")
    return True
