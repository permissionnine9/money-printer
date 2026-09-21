"""
Backend 配置文件

生图/Chat/Agent 模型均由「模型管理」中的默认配置决定；
未配置默认生图模型时，核心素材等生图功能会显式报错。
"""
import logging

logger = logging.getLogger(__name__)


def override_src_config():
    """
    启动时打印实际生效的模型配置（保留函数名用于向后兼容）

    生图/Chat 模型由「模型管理」的默认配置决定；未配置默认时相关功能将报错。
    """
    try:
        from backend.core.persistence import ModelManager
        mgr = ModelManager()
        image_model = mgr.get_default_model("image")
        chat_model = mgr.get_default_model("chat")

        if image_model:
            logger.info(f"当前默认生图模型: {image_model['model_id']} @ {image_model['base_url'] or '内置默认地址'}（模型管理配置）")
        else:
            logger.warning("未配置默认生图模型：核心素材等生图功能将报错，请在「模型管理」配置并设为默认")

        if chat_model:
            logger.info(f"当前默认 Chat 模型: {chat_model['model_id']} @ {chat_model['base_url'] or '内置默认地址'}（模型管理配置）")
        else:
            logger.warning("未配置默认 Chat 模型：chat 相关功能将不可用，请在「模型管理」配置并设为默认")
    except Exception as e:
        logger.warning(f"读取模型管理配置失败: {e}")

    return True
