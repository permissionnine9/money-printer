"""图片生成服务 - 使用胜算云 API 生成图片"""
import uuid
import httpx
import logging

from core.config import (
    SHENGSUANYUN_API_KEY,
    SHENGSUANYUN_BASE_URL,
    SHENGSUANYUN_IMAGE_MODEL,
    SHENGSUANYUN_IMAGE2IMAGE_MODEL,
    SHENGSUANYUN_MATERIAL_IMAGE_MODEL,
    SHENGSUANYUN_MATERIAL_EDIT_MODEL,
)
from core.models import MaterialImage, VideoParams

logger = logging.getLogger(__name__)


class ImageService:
    """图片生成服务类 - 使用胜算云 API"""

    def __init__(self, api_key: str = SHENGSUANYUN_API_KEY):
        self._api_key = api_key
        self._base_url = SHENGSUANYUN_BASE_URL

    def _get_size(self, aspect_ratio: str, resolution: str) -> str:
        """根据宽高比和分辨率获取尺寸（用于文生图 API）"""
        # 胜算云支持的尺寸: 1024x1024、1536x1024、1024x1536
        size_map = {
            "16:9": "1536x1024",  # 横屏
            "9:16": "1024x1536",  # 竖屏
            "1:1": "1024x1024",   # 正方形
            "4:3": "1536x1024",   # 近似横屏
            "3:4": "1024x1536",   # 近似竖屏
        }
        return size_map.get(aspect_ratio, "1024x1024")

    def _get_aspect_ratio_for_i2i(self, aspect_ratio: str) -> str:
        """获取图生图 API 支持的宽高比格式"""
        # Nano Banana 图生图支持的宽高比
        supported = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4", "21:9"]
        if aspect_ratio in supported:
            return aspect_ratio
        # 映射不支持的宽高比
        mapping = {
            "16:10": "16:9",
            "10:16": "9:16",
        }
        return mapping.get(aspect_ratio, "16:9")

    def _get_size_for_material(self, resolution: str) -> str:
        """获取 gemini-3-pro-image-preview 模型支持的尺寸"""
        # gemini-3-pro-image-preview 支持的尺寸: 1K, 2K, 4K
        size_map = {
            "720p": "1K",
            "1080p": "2K",
            "4K": "4K",
        }
        return size_map.get(resolution, "2K")

    def _image_to_base64(self, image_path: str) -> str | None:
        """将图片转换为 base64 格式

        Args:
            image_path: 图片路径（本地路径或URL）

        Returns:
            base64 编码的图片字符串，格式为 data:image/xxx;base64,xxx
        """
        import base64
        import mimetypes
        from pathlib import Path

        try:
            # 如果是URL，直接返回（API 可能支持URL）
            if image_path.startswith(('http://', 'https://')):
                return image_path

            # 本地文件
            path = Path(image_path)
            if not path.exists():
                logger.error(f"图片文件不存在: {image_path}")
                return None

            # 获取 MIME 类型
            mime_type, _ = mimetypes.guess_type(str(path))
            if not mime_type:
                mime_type = "image/png"  # 默认使用 PNG

            # 读取并编码
            with open(path, "rb") as f:
                image_data = f.read()
                base64_str = base64.b64encode(image_data).decode("utf-8")
                return f"data:{mime_type};base64,{base64_str}"

        except Exception as e:
            logger.error(f"转换图片为 base64 失败: {e}")
            return None

    async def query_task_result(self, task_id: str) -> dict:
        """查询任务结果

        Args:
            task_id: 任务ID

        Returns:
            {"success": bool, "status": str, "image_url": str, "error": str}
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        poll_url = f"{self._base_url}/tasks/generations/{task_id}"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(poll_url, headers=headers)

                if response.status_code != 200:
                    logger.warning(f"查询任务失败: HTTP {response.status_code}")
                    return {
                        "success": False,
                        "status": "error",
                        "error": f"HTTP {response.status_code}"
                    }

                result = response.json()
                # API 返回格式：code 表示 API 调用状态，data.status 表示任务状态
                api_code = result.get("code", "").lower()
                data = result.get("data", {})
                task_status = data.get("status", "").upper()

                logger.info(f"任务 {task_id} API状态: {api_code}, 任务状态: {task_status}")

                # 检查 API 调用是否失败
                if api_code not in ("success", ""):
                    error_msg = result.get("error", {}).get("message", result.get("message", "API调用失败"))
                    return {
                        "success": False,
                        "status": "error",
                        "error": error_msg
                    }

                # 检查任务状态
                if task_status == "COMPLETED":
                    image_url = self._extract_image_url(result)
                    if image_url:
                        return {
                            "success": True,
                            "status": "completed",
                            "image_url": image_url
                        }
                    else:
                        return {
                            "success": False,
                            "status": "completed",
                            "error": "图片URL提取失败"
                        }
                elif task_status in ("FAILED", "CANCELLED"):
                    error_msg = data.get("fail_reason") or result.get("message", "任务失败")
                    return {
                        "success": False,
                        "status": "failed",
                        "error": error_msg
                    }
                elif task_status in ("PENDING", "SUBMITTING", "SUBMITTED", "IN_PROGRESS", "PROCESSING", "RUNNING", "QUEUED"):
                    return {
                        "success": False,
                        "status": "pending",
                        "error": "任务仍在处理中，请稍后再试"
                    }
                else:
                    # 未知状态，尝试提取数据
                    if data:
                        image_url = self._extract_image_url(result)
                        if image_url:
                            return {
                                "success": True,
                                "status": "completed",
                                "image_url": image_url
                            }
                    return {
                        "success": False,
                        "status": task_status.lower() if task_status else "unknown",
                        "error": f"未知任务状态: {task_status}"
                    }

        except Exception as e:
            logger.error(f"查询任务异常: {e}")
            return {
                "success": False,
                "status": "error",
                "error": str(e)
            }

    def _extract_image_url(self, result: dict) -> str | None:
        """从结果中提取图片 URL

        Args:
            result: API 返回的结果

        Returns:
            图片 URL，如果提取失败则返回 None
        """
        # 胜算云格式: data.data.image_urls
        data = result.get("data")
        if not isinstance(data, dict):
            return None

        inner_data = data.get("data")
        if isinstance(inner_data, dict):
            image_urls = inner_data.get("image_urls", [])
            if isinstance(image_urls, list) and image_urls:
                return image_urls[0]

        return None

    async def _generate_image(
        self,
        prompt: str,
        video_params: VideoParams,
        timeout: int = 100,
        poll_interval: int = 3
    ) -> dict:
        """生成图片（提交任务并轮询直到完成）

        Args:
            prompt: 图片提示词
            video_params: 视频参数
            timeout: 超时时间（秒），默认40秒
            poll_interval: 轮询间隔（秒），默认3秒

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        import asyncio

        size = self._get_size(video_params.aspect_ratio, video_params.resolution)

        url = f"{self._base_url}/tasks/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = {
            "model": SHENGSUANYUN_IMAGE_MODEL,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "quality": "medium",
            "output_format": "png",
            "output_compression": 100,
            "background": "auto",
            "moderation": "auto",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 1. 提交任务
                logger.info(f"提交图片生成任务: {prompt[:50]}...")
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code not in (200, 201, 202):
                    logger.error(f"图片生成失败: HTTP {response.status_code} - {response.text}")
                    return {"success": False, "error": f"HTTP {response.status_code}"}

                result = response.json()
                logger.info(f"提交响应: {result}")

                # 2. 异步任务，获取 request_id 并轮询
                data = result.get('data')
                if isinstance(data, dict):
                    request_id = data.get('request_id')
                else:
                    # data 可能是字符串或其他类型，尝试从根级别获取
                    request_id = result.get('request_id') or result.get('id') or result.get('task_id')
                if not request_id:
                    logger.error(f"无法获取任务ID: {result}")
                    return {"success": False, "error": "无法获取任务ID"}

                logger.info(f"获得任务ID: {request_id}，开始轮询...")

                # 3. 轮询等待结果
                elapsed = 0
                while elapsed < timeout:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval

                    query_result = await self.query_task_result(request_id)
                    status = query_result.get("status")

                    if query_result.get("success"):
                        image_url = query_result.get("image_url")
                        logger.info(f"任务完成，图片URL: {image_url}")
                        return {"success": True, "image_url": image_url}

                    if status == "failed":
                        logger.error(f"任务失败: {query_result.get('error')}")
                        return {"success": False, "error": query_result.get("error", "任务失败")}

                    if status == "completed":
                        # 已完成但提取图片失败
                        logger.error(f"任务已完成但处理失败: {query_result.get('error')}")
                        return {"success": False, "error": query_result.get("error", "图片URL提取失败")}

                    if status == "pending":
                        logger.info(f"任务处理中... ({elapsed}s/{timeout}s)")
                        continue

                    # 未知状态，尝试返回错误
                    logger.warning(f"未知状态: {status}，返回错误")
                    return {"success": False, "error": f"未知状态: {status}"}

                # 超时
                logger.error(f"任务超时 ({timeout}s)")
                return {"success": False, "error": f"任务超时 ({timeout}s)"}

        except Exception as e:
            logger.error(f"图片生成异常: {e}")
            return {"success": False, "error": str(e)}

    async def submit_i2i_task(
        self,
        prompt: str,
        reference_images: list[str],
        video_params: VideoParams,
    ) -> dict:
        """提交图生图任务（只提交，不轮询）

        Args:
            prompt: 图片提示词
            reference_images: 参考图路径列表（本地路径或URL）
            video_params: 视频参数

        Returns:
            {"success": bool, "request_id": str, "error": str}
        """
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
            return {"success": False, "error": "没有有效的参考图"}

        url = f"{self._base_url}/tasks/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = {
            "model": SHENGSUANYUN_IMAGE2IMAGE_MODEL,
            "prompt": prompt,
            "images": images_data,
            "aspect_ratio": aspect_ratio,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                logger.info(f"提交图生图任务: {prompt[:50]}... (参考图: {len(reference_images)}张)")
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code not in (200, 201, 202):
                    logger.error(f"图生图失败: HTTP {response.status_code} - {response.text}")
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

                logger.info(f"任务已提交，request_id: {request_id}")
                return {"success": True, "request_id": request_id}

        except Exception as e:
            logger.error(f"提交图生图任务异常: {e}")
            return {"success": False, "error": str(e)}

    async def poll_i2i_task(
        self,
        request_id: str,
        timeout: int = 60,
        poll_interval: int = 3
    ) -> dict:
        """轮询图生图任务结果

        Args:
            request_id: 任务ID
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        import asyncio

        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            query_result = await self.query_task_result(request_id)
            status = query_result.get("status")

            if query_result.get("success"):
                image_url = query_result.get("image_url")
                logger.info(f"图生图完成 [{request_id}]，图片URL: {image_url}")
                return {"success": True, "image_url": image_url}

            if status == "failed":
                logger.error(f"任务失败 [{request_id}]: {query_result.get('error')}")
                return {"success": False, "error": query_result.get("error", "任务失败")}

            if status == "completed":
                # 已完成但提取图片失败
                logger.error(f"任务已完成但处理失败 [{request_id}]: {query_result.get('error')}")
                return {"success": False, "error": query_result.get("error", "图片URL提取失败")}

            if status == "pending":
                logger.info(f"任务处理中 [{request_id}]... ({elapsed}s/{timeout}s)")
                continue

            logger.warning(f"未知状态 [{request_id}]: {status}，尝试返回错误")
            return {"success": False, "error": f"未知状态: {status}"}

        logger.error(f"任务超时 [{request_id}] ({timeout}s)")
        return {"success": False, "error": f"任务超时 ({timeout}s)"}

    async def _generate_image_with_reference(
        self,
        prompt: str,
        reference_images: list[str],
        video_params: VideoParams,
        timeout: int = 60,
        poll_interval: int = 3
    ) -> dict:
        """基于参考图生成图片（图生图）- 提交并等待完成

        Args:
            prompt: 图片提示词，可以引用参考图，如"基于参考图中的角色..."
            reference_images: 参考图URL列表
            video_params: 视频参数
            timeout: 超时时间（秒），默认60秒
            poll_interval: 轮询间隔（秒），默认3秒

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        # 1. 提交任务
        submit_result = await self.submit_i2i_task(prompt, reference_images, video_params)
        if not submit_result.get("success"):
            return submit_result

        # 2. 轮询等待结果
        request_id = submit_result["request_id"]
        return await self.poll_i2i_task(request_id, timeout, poll_interval)

    async def _generate_material_image_with_reference(
        self,
        prompt: str,
        reference_images: list[str],
        video_params: VideoParams,
        timeout: int = 180,
        poll_interval: int = 5
    ) -> dict:
        """使用 gemini-3-pro-image-preview 模型基于参考图生成素材图

        Args:
            prompt: 图片提示词
            reference_images: 用户上传的参考图路径列表（支持本地路径和URL）
            video_params: 视频参数
            timeout: 超时时间（秒），默认180秒
            poll_interval: 轮询间隔（秒），默认5秒

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        import asyncio

        # 获取尺寸和宽高比
        size = self._get_size_for_material(video_params.resolution)
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

        payload = {
            "model": SHENGSUANYUN_MATERIAL_IMAGE_MODEL,
            "prompt": prompt,
            "size": size,
            "aspect_ratio": aspect_ratio,
        }

        # 如果有参考图，添加到请求中
        if images_data:
            payload["images"] = images_data

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                logger.info(f"提交素材图生成任务 (gemini-3-pro): {prompt[:50]}... (参考图: {len(images_data)}张)")
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
                        # 已完成但提取图片失败
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

    
    async def generate_material_images_with_reference(
        self,
        prompts_data: list[dict],
        video_params: VideoParams,
        reference_images: list[str] | None = None
    ) -> list[MaterialImage]:
        """生成素材图片（支持用户上传参考图，使用 gemini-3-pro-image-preview）

        Args:
            prompts_data: 提示词数据列表，每项包含:
                - prompt: 英文提示词
                - description: 中文描述
                - type: 素材图类型 (character/props/environment/general)
            video_params: 视频参数
            reference_images: 用户上传的参考图路径列表（可选）

        Returns:
            生成的素材图列表
        """
        results = []
        type_names = {
            "character": "角色设定图",  # 兼容旧类型
            "character_main": "主要角色设定图",
            "character_minor": "边缘角色设定图",
            "props": "物品/道具设定图",
            "environment": "场景设定图",  # 兼容旧类型
            "environment_main": "主场景设定图",
            "environment_minor": "副场景设定图",
            "general": "素材图"
        }

        for i, item in enumerate(prompts_data):
            # 兼容旧格式（纯字符串）
            if isinstance(item, str):
                prompt = item
                description = f"素材图 {i + 1}"
                image_type = "general"
            else:
                prompt = item.get("prompt", "")
                description = item.get("description", f"素材图 {i + 1}")
                image_type = item.get("type", "general")

            # 素材图提示词增强
            styled_prompt = f"{prompt}, high quality, detailed, professional concept art"

            # 如果有参考图，在提示词中说明
            if reference_images:
                styled_prompt = f"Based on the reference images provided, {styled_prompt}"

            type_name = type_names.get(image_type, "素材图")

            try:
                image_id = str(uuid.uuid4())

                logger.info(f"生成{type_name} {i + 1}/{len(prompts_data)} (使用 gemini-3-pro-image-preview)...")

                # 使用新的 gemini-3-pro-image-preview 方法
                result = await self._generate_material_image_with_reference(
                    styled_prompt,
                    reference_images or [],
                    video_params
                )

                if result.get("success"):
                    results.append(MaterialImage(
                        image_id=image_id,
                        image_path=result.get("image_url", ""),
                        prompt=styled_prompt,
                        description=description,
                        image_type=image_type,
                        task_id="",
                        task_status="completed"
                    ))
                else:
                    results.append(MaterialImage(
                        image_id=f"error_{i}",
                        image_path="",
                        prompt=styled_prompt,
                        description=f"生成失败: {result.get('error', '未知错误')}",
                        image_type=image_type,
                        task_id="",
                        task_status="failed"
                    ))

            except Exception as e:
                logger.error(f"生成{type_name} {i + 1} 失败: {e}")
                results.append(MaterialImage(
                    image_id=f"error_{i}",
                    image_path="",
                    prompt=styled_prompt,
                    description=f"生成失败: {str(e)}",
                    image_type=image_type,
                    task_id="",
                    task_status="failed"
                ))

        return results

    async def generate_material_images(
        self,
        prompts_data: list[dict],
        video_params: VideoParams,
        reference_images: list[str] | None = None
    ) -> list[MaterialImage]:
        """生成素材图片（设定稿风格）

        如果提供了参考图，将使用 gemini-3-pro-image-preview 模型进行图生图；
        否则使用默认的文生图模型。

        Args:
            prompts_data: 提示词数据列表，每项包含:
                - prompt: 英文提示词
                - description: 中文描述
                - type: 素材图类型 (character/props/environment/general)
            video_params: 视频参数
            reference_images: 用户上传的参考图路径列表（可选，支持本地路径和URL）

        Returns:
            生成的素材图列表
        """
        # 如果有参考图，使用 gemini-3-pro-image-preview 模型
        if reference_images and len(reference_images) > 0:
            logger.info(f"检测到 {len(reference_images)} 张参考图，使用 gemini-3-pro-image-preview 模型")
            return await self.generate_material_images_with_reference(
                prompts_data, video_params, reference_images
            )

        # 没有参考图，使用原来的文生图方法
        results = []
        type_names = {
            "character": "角色设定图",  # 兼容旧类型
            "character_main": "主要角色设定图",
            "character_minor": "边缘角色设定图",
            "props": "物品/道具设定图",
            "environment": "场景设定图",  # 兼容旧类型
            "environment_main": "主场景设定图",
            "environment_minor": "副场景设定图",
            "general": "素材图"
        }

        for i, item in enumerate(prompts_data):
            # 兼容旧格式（纯字符串）
            if isinstance(item, str):
                prompt = item
                description = f"素材图 {i + 1}"
                image_type = "general"
            else:
                prompt = item.get("prompt", "")
                description = item.get("description", f"素材图 {i + 1}")
                image_type = item.get("type", "general")

            # 素材图不需要额外添加 style，因为 LLM 已经在 prompt 中指定了
            styled_prompt = f"{prompt}, high quality, detailed, professional concept art"

            type_name = type_names.get(image_type, "素材图")

            try:
                image_id = str(uuid.uuid4())

                logger.info(f"生成{type_name} {i + 1}/{len(prompts_data)} (文生图模式)...")
                result = await self._generate_image(styled_prompt, video_params)

                if result.get("success"):
                    results.append(MaterialImage(
                        image_id=image_id,
                        image_path=result.get("image_url", ""),
                        prompt=styled_prompt,
                        description=description,
                        image_type=image_type,
                        task_id="",
                        task_status="completed"
                    ))
                else:
                    results.append(MaterialImage(
                        image_id=f"error_{i}",
                        image_path="",
                        prompt=styled_prompt,
                        description=f"生成失败: {result.get('error', '未知错误')}",
                        image_type=image_type,
                        task_id="",
                        task_status="failed"
                    ))

            except Exception as e:
                logger.error(f"生成{type_name} {i + 1} 失败: {e}")
                results.append(MaterialImage(
                    image_id=f"error_{i}",
                    image_path="",
                    prompt=styled_prompt,
                    description=f"生成失败: {str(e)}",
                    image_type=image_type,
                    task_id="",
                    task_status="failed"
                ))

        return results

    def build_frame_prompt(
        self,
        prompt: str,
        video_params: VideoParams,
        frame_type: str = "",
    ) -> str:
        """构建首尾帧的图生图提示词

        Args:
            prompt: 原始提示词
            video_params: 视频参数
            frame_type: 帧类型，"first" 或 "last"

        Returns:
            构建好的完整提示词
        """
        styled_prompt = f"{prompt}, {video_params.style} style, high quality"

        frame_context = ""
        if frame_type == "first":
            frame_context = (
                "This is the FIRST FRAME (opening shot) of a video segment, "
                "capturing the beginning state of the action. "
            )
        elif frame_type == "last":
            frame_context = (
                "This is the LAST FRAME (ending shot) of a video segment, "
                "capturing the final state after the action is completed. "
            )

        i2i_prompt = (
            f"{frame_context}"
            f"Based on the reference images, generate: {styled_prompt}. "
            f"Keep the same characters, objects, and visual style from the reference images. "
            f"IMPORTANT: Do NOT include any annotations, labels, text, height rulers, size measurements, "
            f"scale bars, dimension markers, or reference sheet elements. "
            f"Generate a clean cinematic frame suitable for video production, not a design sheet."
        )
        return i2i_prompt

    async def generate_single_image(
        self,
        prompt: str,
        video_params: VideoParams,
        prefix: str = "",
        reference_images: list[str] | None = None,
        frame_type: str = "",
    ) -> tuple[str, str]:
        """生成单张图片（支持图生图）

        Args:
            prompt: 图片提示词
            video_params: 视频参数
            prefix: 图片标识前缀（用于日志）
            reference_images: 参考图URL列表（素材图），用于保持角色/物品一致性
            frame_type: 帧类型，"first" 表示首帧，"last" 表示尾帧，用于在提示词中强调

        返回: (image_id, image_url)
        """
        styled_prompt = f"{prompt}, {video_params.style} style, high quality"
        use_i2i = reference_images and len(reference_images) > 0

        try:
            image_id = str(uuid.uuid4())
            log_prefix = f"[{prefix}] " if prefix else ""
            logger.info(f"{log_prefix}开始生成图片 ({'图生图' if use_i2i else '文生图'})...")

            if use_i2i:
                i2i_prompt = self.build_frame_prompt(prompt, video_params, frame_type)
                result = await self._generate_image_with_reference(
                    i2i_prompt,
                    reference_images,
                    video_params
                )
            else:
                # 降级到文生图
                result = await self._generate_image(styled_prompt, video_params)

            if result.get("success"):
                return image_id, result.get("image_url", "")

        except Exception as e:
            logger.error(f"生成图片失败: {e}")

        return "error", ""

    async def _generate_image_with_base64_i2i(
        self,
        prompt: str,
        images_data: list[str],
        video_params: VideoParams,
        timeout: int = 180,
        poll_interval: int = 5
    ) -> dict:
        """使用 gemini-2.5-flash-image 模型基于base64或URL进行图生图

        Args:
            prompt: 图片提示词
            images_data: 图片数据列表（可以是base64 data URL或http URL）
            video_params: 视频参数
            timeout: 超时时间（秒），默认180秒
            poll_interval: 轮询间隔（秒），默认5秒

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        import asyncio

        # 获取宽高比（gemini-2.5-flash-image 使用 aspect_ratio，不支持 size）
        aspect_ratio = self._get_aspect_ratio_for_i2i(video_params.aspect_ratio)

        url = f"{self._base_url}/tasks/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        payload = {
            "model": SHENGSUANYUN_IMAGE2IMAGE_MODEL,  # google/gemini-2.5-flash-image
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "images": images_data,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                logger.info(f"提交图生图任务 (gemini-2.5-flash-image): {prompt[:50]}... (参考图: {len(images_data)}张)")
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code not in (200, 201, 202):
                    logger.error(f"图生图失败: HTTP {response.status_code} - {response.text}")
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
                        logger.info(f"图生图完成，URL: {image_url}")
                        return {"success": True, "image_url": image_url}

                    if status == "failed":
                        logger.error(f"任务失败: {query_result.get('error')}")
                        return {"success": False, "error": query_result.get("error", "任务失败")}

                    if status == "completed":
                        # 已完成但提取图片失败
                        logger.error(f"图生图已完成但处理失败: {query_result.get('error')}")
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
            logger.error(f"图生图异常: {e}")
            return {"success": False, "error": str(e)}

    def _get_jimeng_v40_size_params(self, aspect_ratio: str, resolution: str) -> dict:
        """获取即梦 v40 模型的尺寸参数

        Args:
            aspect_ratio: 宽高比，如 "16:9", "9:16", "1:1"
            resolution: 分辨率，如 "720p", "1080p", "4K"

        Returns:
            包含 width, height, size 的字典
        """
        # 即梦 v40 支持的 size 格式: "2k(16:9)", "2k(9:16)", "2k(1:1)" 等
        # 根据分辨率选择基础尺寸
        size_prefix_map = {
            "720p": "1k",
            "1080p": "2k",
            "4K": "4k",
        }
        size_prefix = size_prefix_map.get(resolution, "2k")

        # 构建 size 字符串
        size = f"{size_prefix}({aspect_ratio})"

        # 预定义的尺寸映射（基于2k分辨率）
        dimension_map = {
            "16:9": {"width": 1664, "height": 936},
            "9:16": {"width": 936, "height": 1664},
            "1:1": {"width": 1024, "height": 1024},
            "4:3": {"width": 1280, "height": 960},
            "3:4": {"width": 960, "height": 1280},
            "3:2": {"width": 1536, "height": 1024},
            "2:3": {"width": 1024, "height": 1536},
            "21:9": {"width": 1792, "height": 768},
        }

        base_dims = dimension_map.get(aspect_ratio, {"width": 1664, "height": 936})

        # 根据分辨率调整尺寸
        scale_factor = {
            "720p": 0.75,
            "1080p": 1.0,
            "4K": 2.0,
        }.get(resolution, 1.0)

        return {
            "width": int(base_dims["width"] * scale_factor),
            "height": int(base_dims["height"] * scale_factor),
            "size": size,
        }

    async def _ensure_image_urls(self, image_paths: list[str]) -> list[str]:
        """确保图片路径都是URL格式

        对于本地文件，尝试上传到OSS获取URL。

        Args:
            image_paths: 图片路径列表（可能是URL或本地路径）

        Returns:
            URL列表
        """
        from core.services.oss_service import get_oss_service
        from core.config import OSS_ACCESS_KEY, OSS_BUCKET
        import os

        urls = []

        for img_path in image_paths:
            if not img_path:
                continue

            # 如果已经是URL，直接使用
            if img_path.startswith(('http://', 'https://')):
                urls.append(img_path)
                logger.info(f"[即梦v40] 使用现有URL: {img_path[:80]}...")
                continue

            # 本地文件需要上传到OSS
            if not os.path.exists(img_path):
                logger.warning(f"[即梦v40] 本地文件不存在，跳过: {img_path}")
                continue

            # 检查OSS是否配置
            if not OSS_ACCESS_KEY or not OSS_BUCKET:
                logger.warning(f"[即梦v40] OSS未配置，无法上传本地文件: {img_path}")
                # 无法使用本地文件，跳过
                continue

            try:
                oss_service = get_oss_service()
                url = await oss_service.upload_file(
                    local_path=img_path,
                    remote_dir="material_edit_temp",
                    content_type="image/png" if img_path.endswith('.png') else "image/jpeg"
                )
                urls.append(url)
                logger.info(f"[即梦v40] 本地文件已上传到OSS: {img_path} -> {url[:80]}...")
            except Exception as e:
                logger.error(f"[即梦v40] 上传文件到OSS失败: {e}")
                continue

        return urls

    async def _generate_image_with_jimeng_v40_i2i(
        self,
        prompt: str,
        image_urls: list[str],
        video_params: VideoParams,
        scale: float = 0.9,
        timeout: int = 180,
        poll_interval: int = 5
    ) -> dict:
        """使用即梦 v40 模型进行图生图

        Args:
            prompt: 图片提示词
            image_urls: 参考图URL列表（必须是有效的URL）
            video_params: 视频参数
            scale: 图片与参考图的相似度，0-1之间，越大越相似
            timeout: 超时时间（秒），默认180秒
            poll_interval: 轮询间隔（秒），默认5秒

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        import asyncio

        # 获取尺寸参数
        size_params = self._get_jimeng_v40_size_params(
            video_params.aspect_ratio,
            video_params.resolution
        )

        url = f"{self._base_url}/tasks/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        payload = {
            "model": SHENGSUANYUN_MATERIAL_EDIT_MODEL,  # bytedance/jimeng_v40
            "prompt": prompt,
            "image_urls": image_urls,
            "width": size_params["width"],
            "height": size_params["height"],
            "size": size_params["size"],
            "scale": scale,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                logger.info(f"[即梦v40] 提交图生图任务: {prompt[:50]}... (参考图: {len(image_urls)}张)")
                logger.info(f"[即梦v40] 尺寸参数: {size_params}, scale: {scale}")
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code not in (200, 201, 202):
                    logger.error(f"[即梦v40] 提交失败: HTTP {response.status_code} - {response.text}")
                    return {"success": False, "error": f"HTTP {response.status_code}"}

                result = response.json()
                logger.info(f"[即梦v40] 提交响应: {result}")

                # 获取任务ID
                data = result.get('data')
                if isinstance(data, dict):
                    request_id = data.get('request_id')
                else:
                    request_id = result.get('request_id') or result.get('id') or result.get('task_id')

                if not request_id:
                    logger.error(f"[即梦v40] 无法获取任务ID: {result}")
                    return {"success": False, "error": "无法获取任务ID"}

                logger.info(f"[即梦v40] 获得任务ID: {request_id}，开始轮询...")

                # 轮询等待结果
                elapsed = 0
                while elapsed < timeout:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval

                    query_result = await self.query_task_result(request_id)
                    status = query_result.get("status")

                    if query_result.get("success"):
                        image_url = query_result.get("image_url")
                        logger.info(f"[即梦v40] 任务完成，URL: {image_url}")
                        return {"success": True, "image_url": image_url}

                    if status == "failed":
                        logger.error(f"[即梦v40] 任务失败: {query_result.get('error')}")
                        return {"success": False, "error": query_result.get("error", "任务失败")}

                    if status == "completed":
                        logger.error(f"[即梦v40] 任务已完成但处理失败: {query_result.get('error')}")
                        return {"success": False, "error": query_result.get("error", "图片URL提取失败")}

                    if status == "pending":
                        logger.info(f"[即梦v40] 任务处理中... ({elapsed}s/{timeout}s)")
                        continue

                    logger.warning(f"[即梦v40] 未知状态: {status}，返回错误")
                    return {"success": False, "error": f"未知状态: {status}"}

                # 超时
                logger.error(f"[即梦v40] 任务超时 ({timeout}s)")
                return {"success": False, "error": f"任务超时 ({timeout}s)"}

        except Exception as e:
            logger.error(f"[即梦v40] 图生图异常: {e}")
            return {"success": False, "error": str(e)}

    async def edit_material_image(
        self,
        original_image_path: str,
        edit_prompt: str,
        video_params: VideoParams,
        reference_images: list[str] | None = None,
        original_prompt: str | None = None,
        timeout: int = 180,
        poll_interval: int = 5
    ) -> dict:
        """编辑单个素材图（使用即梦 v40 模型进行图生图）

        支持用户完全控制参考图列表，实现高度自由的编辑。
        如果用户提供了reference_images，则使用用户提供的参考图；
        如果用户没有提供参考图，则使用original_image_path作为保底。

        注意：即梦 v40 只支持 URL 格式的图片，本地文件需要先上传到 OSS。

        Args:
            original_image_path: 原始素材图路径（本地路径或URL），当reference_images为空时作为保底使用
            edit_prompt: 编辑提示词，描述想要做的修改，例如："更鲜艳的颜色"、"添加笑容"、"卡通风格"等
            video_params: 视频参数
            reference_images: 用户选择的参考图路径列表（可选），用户可自由决定是否包含原素材图
            original_prompt: 原始生成提示词（可选），用于保持原素材图的上下文
            timeout: 超时时间（秒），默认180秒
            poll_interval: 轮询间隔（秒），默认5秒

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        logger.info(f"[素材图编辑] 开始编辑素材图（使用即梦v40）: {edit_prompt[:50]}...")
        if original_prompt:
            logger.info(f"[素材图编辑] 原始提示词: {original_prompt[:100]}...")

        # 确定最终使用的参考图列表
        # 如果用户提供了reference_images，使用用户提供的；否则使用原素材图作为保底
        if reference_images and len(reference_images) > 0:
            all_reference_images = reference_images
            logger.info(f"[素材图编辑] 使用用户选择的 {len(reference_images)} 张参考图")
        else:
            all_reference_images = [original_image_path]
            logger.info(f"[素材图编辑] 用户未选择参考图，使用原素材图作为保底")

        # 构建完整提示词：结合原始提示词和编辑提示词
        # 即梦 v40 模型的提示词格式更简洁
        if original_prompt:
            full_prompt = f"""基于原始概念: {original_prompt}

根据以下要求编辑这张设计参考图: {edit_prompt}

要求:
- 保持原始角色/物品/场景的设计结构和关键视觉元素
- 保持一致的艺术风格、色彩搭配和视觉氛围
- 确保高质量、细节丰富的插画
- 避免添加文字标注、标签、标尺或测量标记
- 输出干净的设计参考图"""
        else:
            # 没有原始提示词，直接使用编辑提示词
            full_prompt = f"""根据以下要求编辑这张设计参考图: {edit_prompt}

要求:
- 保持整体设计结构和关键视觉元素
- 确保高质量、细节丰富的插画
- 避免添加文字标注、标签、标尺或测量标记
- 输出干净的设计参考图"""

        logger.info(f"[素材图编辑] 总共需要处理 {len(all_reference_images)} 张参考图")

        # 将所有参考图转换为URL格式（即梦v40只支持URL）
        image_urls = await self._ensure_image_urls(all_reference_images)

        if not image_urls:
            return {"success": False, "error": "没有有效的参考图URL（即梦v40只支持URL格式，本地文件需要配置OSS上传）"}

        logger.info(f"[素材图编辑] 共 {len(image_urls)} 张参考图（URL格式）")

        # 使用即梦 v40 模型的图生图功能
        result = await self._generate_image_with_jimeng_v40_i2i(
            prompt=full_prompt,
            image_urls=image_urls,
            video_params=video_params,
            scale=0.9,  # 保持较高的相似度
            timeout=timeout,
            poll_interval=poll_interval
        )

        if result.get("success"):
            logger.info(f"[素材图编辑] 编辑成功，新图URL: {result.get('image_url')}")
        else:
            logger.error(f"[素材图编辑] 编辑失败: {result.get('error')}")

        return result
