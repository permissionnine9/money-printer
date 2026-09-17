"""
Backend 配置文件

图片/LLM 模型实际生效优先级：模型管理中的默认配置 > 系统内置常量
（见 workflow_v2.build_image_service_from_model_config 与 VideoCreationWorkflowV2.__init__）
"""
import logging

logger = logging.getLogger(__name__)


def override_src_config():
    """
    启动时打印实际生效的模型配置（保留函数名用于向后兼容）

    生图/Chat 模型由「模型管理」的默认配置决定；未配置默认时回退系统内置常量。
    """
    try:
        from backend.core.persistence import ModelManager
        mgr = ModelManager()
        image_model = mgr.get_default_model("image")
        chat_model = mgr.get_default_model("chat")

        if image_model:
            logger.info(f"当前默认生图模型: {image_model['model_id']} @ {image_model['base_url'] or '系统默认地址'}（模型管理配置）")
        else:
            logger.info("当前默认生图模型: 系统内置配置（可在「模型管理」中配置默认生图模型）")

        if chat_model:
            logger.info(f"当前默认 Chat 模型: {chat_model['model_id']} @ {chat_model['base_url'] or '系统默认地址'}（模型管理配置）")
        else:
            logger.info("当前默认 Chat 模型: 系统内置配置（可在「模型管理」中配置默认 Chat 模型）")
    except Exception as e:
        logger.warning(f"读取模型管理配置失败，使用系统内置配置: {e}")

    return True
