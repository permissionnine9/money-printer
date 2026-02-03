"""
Backend 配置文件
覆盖 src/config.py 中的特定配置
"""
import logging

logger = logging.getLogger(__name__)

# 素材图生成模型配置
# 将 gemini-3-pro-image-preview 改为 gemini-2.5-flash-image
SHENGSUANYUN_MATERIAL_IMAGE_MODEL = "google/gemini-2.5-flash-image"


async def _generate_material_image_with_reference_patched(
    self,
    prompt: str,
    reference_images: list[str],
    video_params,
    timeout: int = 180,
    poll_interval: int = 5
) -> dict:
    """
    使用 gemini-2.5-flash-image 模型基于参考图生成素材图（ patched 版本）
    
    与原版区别：
    1. 移除了 size 参数（gemini-2.5-flash-image 不支持）
    2. 只使用 aspect_ratio 参数
    3. 更新了日志信息
    """
    import asyncio
    import httpx
    
    # 获取宽高比（gemini-2.5-flash-image 只需要 aspect_ratio）
    aspect_ratio = self._get_aspect_ratio_for_i2i(video_params.aspect_ratio)

    # 将参考图转换为 base64 或保持URL
    images_data = []
    for img_path in reference_images:
        img_data = self._image_to_base64(img_path)
        if img_data:
            images_data.append(img_data)
        else:
            logger.warning(f"跳过无效的参考图: {img_path}")

    if not images_data:
        logger.warning("没有有效的参考图，将使用纯文生图")

    url = f"{self._base_url}/tasks/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {self._api_key}",
    }

    # 构建 payload：gemini-2.5-flash-image 只使用 aspect_ratio，不使用 size
    payload = {
        "model": SHENGSUANYUN_MATERIAL_IMAGE_MODEL,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
    }

    # 如果有参考图，添加到请求中
    if images_data:
        payload["images"] = images_data

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            logger.info(f"提交素材图生成任务 (gemini-2.5-flash-image): {prompt[:50]}... (参考图: {len(images_data)}张)")
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code not in (200, 201, 202):
                logger.error(f"素材图生成失败: HTTP {response.status_code} - {response.text}")
                return {"success": False, "error": f"HTTP {response.status_code}"}

            result = response.json()
            logger.info(f"提交响应: {result}")

            # 获取任务ID
            data = result.get('data')
            if isinstance(data, dict):
                request_id = data.get('request_id')
            else:
                request_id = result.get('request_id') or result.get('id') or result.get('task_id')

            if not request_id:
                logger.error(f"无法获取任务ID: {result}")
                return {"success": False, "error": "无法获取任务ID"}

            logger.info(f"获得任务ID: {request_id}，开始轮询...")

            # 轮询等待结果
            elapsed = 0
            while elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                query_result = await self.query_task_result(request_id)
                status = query_result.get("status")

                if query_result.get("success"):
                    image_url = query_result.get("image_url")
                    logger.info(f"素材图生成完成，URL: {image_url}")
                    return {"success": True, "image_url": image_url}

                if status == "failed":
                    logger.error(f"任务失败: {query_result.get('error')}")
                    return {"success": False, "error": query_result.get("error", "任务失败")}

                if status == "completed":
                    logger.error(f"素材图已完成但处理失败: {query_result.get('error')}")
                    return {"success": False, "error": query_result.get("error", "图片URL提取失败")}

                if status == "pending":
                    logger.info(f"任务处理中... ({elapsed}s/{timeout}s)")
                    continue

                logger.warning(f"未知状态: {status}，返回错误")
                return {"success": False, "error": f"未知状态: {status}"}

            # 超时
            logger.error(f"任务超时 ({timeout}s)")
            return {"success": False, "error": f"任务超时 ({timeout}s)"}

    except Exception as e:
        logger.error(f"素材图生成异常: {e}")
        return {"success": False, "error": str(e)}


def override_src_config():
    """
    覆盖 src/config.py 和 src/services/image_service.py 中的配置和方法
    在应用启动时调用
    """
    import core.config as src_config
    from core.services import image_service as image_service_module
    from core.services.image_service import ImageService
    
    # 1. 覆盖配置变量
    src_config.SHENGSUANYUN_MATERIAL_IMAGE_MODEL = SHENGSUANYUN_MATERIAL_IMAGE_MODEL
    image_service_module.SHENGSUANYUN_MATERIAL_IMAGE_MODEL = SHENGSUANYUN_MATERIAL_IMAGE_MODEL
    
    # 2. Monkey-patch ImageService._generate_material_image_with_reference 方法
    ImageService._generate_material_image_with_reference = _generate_material_image_with_reference_patched
    
    logger.info(f"Backend 配置已覆盖: MATERIAL_IMAGE_MODEL = {SHENGSUANYUN_MATERIAL_IMAGE_MODEL}")
    logger.info("ImageService._generate_material_image_with_reference 已替换为 patched 版本")
    
    return True
