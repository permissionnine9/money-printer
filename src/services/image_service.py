"""图片生成服务 - 使用胜算云 API 生成图片"""
import uuid
import httpx
import logging

from src.config import (
    SHENGSUANYUN_API_KEY,
    SHENGSUANYUN_BASE_URL,
    SHENGSUANYUN_IMAGE_MODEL,
    SHENGSUANYUN_IMAGE2IMAGE_MODEL,
)
from src.models import MaterialImage, VideoParams

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
                status = result.get("code", "").lower()

                logger.info(f"任务 {task_id} 状态: {status}")

                # 检查任务状态
                if status == "success":
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
                elif status in ("failed", "error", "cancelled"):
                    error_msg = result.get("error", result.get("message", "任务失败"))
                    return {
                        "success": False,
                        "status": "failed",
                        "error": error_msg
                    }
                elif status in ("pending", "processing", "running", "in_progress", "queued"):
                    return {
                        "success": False,
                        "status": "pending",
                        "error": "任务仍在处理中，请稍后再试"
                    }
                else:
                    # 未知状态，尝试提取数据
                    if "data" in result and result["data"]:
                        image_url = self._extract_image_url(result)
                        if image_url:
                            return {
                                "success": True,
                                "status": "completed",
                                "image_url": image_url
                            }
                    return {
                        "success": False,
                        "status": status,
                        "error": f"未知状态: {status}"
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

                    if status == "pending":
                        logger.info(f"任务处理中... ({elapsed}s/{timeout}s)")
                        continue

                    # 未知状态，继续等待
                    logger.warning(f"未知状态: {status}，继续等待...")

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
            reference_images: 参考图URL列表
            video_params: 视频参数

        Returns:
            {"success": bool, "request_id": str, "error": str}
        """
        aspect_ratio = self._get_aspect_ratio_for_i2i(video_params.aspect_ratio)

        url = f"{self._base_url}/tasks/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = {
            "model": SHENGSUANYUN_IMAGE2IMAGE_MODEL,
            "prompt": prompt,
            "images": reference_images,
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
        timeout: int = 120,
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

            if status == "pending":
                logger.info(f"任务处理中 [{request_id}]... ({elapsed}s/{timeout}s)")
                continue

            logger.warning(f"未知状态 [{request_id}]: {status}，继续等待...")

        logger.error(f"任务超时 [{request_id}] ({timeout}s)")
        return {"success": False, "error": f"任务超时 ({timeout}s)"}

    async def _generate_image_with_reference(
        self,
        prompt: str,
        reference_images: list[str],
        video_params: VideoParams,
        timeout: int = 120,
        poll_interval: int = 3
    ) -> dict:
        """基于参考图生成图片（图生图）- 提交并等待完成

        Args:
            prompt: 图片提示词，可以引用参考图，如"基于参考图中的角色..."
            reference_images: 参考图URL列表
            video_params: 视频参数
            timeout: 超时时间（秒），默认120秒
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

    async def generate_material_images(
        self,
        prompts_data: list[dict],
        video_params: VideoParams
    ) -> list[MaterialImage]:
        """生成素材图片（设定稿风格）

        Args:
            prompts_data: 提示词数据列表，每项包含:
                - prompt: 英文提示词
                - description: 中文描述
                - type: 素材图类型 (character/props/environment/general)
            video_params: 视频参数

        Returns:
            生成的素材图列表
        """
        results = []
        type_names = {
            "character": "角色设定图",
            "props": "物品设定图",
            "environment": "场景设定图",
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

                logger.info(f"生成{type_name} {i + 1}/{len(prompts_data)}...")
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
