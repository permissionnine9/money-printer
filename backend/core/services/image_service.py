"""图片生成服务 - 使用胜算云 API 生成图片"""
import asyncio
import base64
import io
import mimetypes
import uuid
from pathlib import Path

import httpx
from PIL import Image

from backend.core.config import (
    SHENGSUANYUN_API_KEY,
    SHENGSUANYUN_BASE_URL,
    SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP,
)
from backend.core.models import MaterialImage, VideoParams

import logging
logger = logging.getLogger(__name__)

# 图片压缩配置
IMAGE_COMPRESS_MAX_SIZE = 1920  # 最大边长（像素）
IMAGE_COMPRESS_QUALITY = 85    # JPEG 压缩质量（1-100）

# 生图模型未配置的统一报错文案
_NOT_CONFIGURED_MSG = "生图模型未配置（缺少 API Key 或模型 ID），请在「模型管理」完成配置"


class ImageModelNotConfiguredError(RuntimeError):
    """生图模型未配置（无默认 image 模型 / 缺 API Key / 缺模型 ID）"""


def build_image_service_from_model_config(model_config_id: str | None = None) -> "ImageService":
    """唯一的生图服务工厂：按「模型管理」配置构造 ImageService，未配置或不完整时显式报错

    Args:
        model_config_id: 模型配置ID；为 None 时读取默认生图模型配置

    Returns:
        配置好的 ImageService 实例

    Raises:
        ImageModelNotConfiguredError: 无配置 / 配置不存在 / 缺 API Key / 缺模型 ID
    """
    from backend.core.persistence import ModelManager

    manager = ModelManager()
    if model_config_id:
        config = manager.get_model(model_config_id)
        if not config:
            raise ImageModelNotConfiguredError(f"生图模型配置不存在: {model_config_id}")
    else:
        config = manager.get_default_model(model_type="image")

    if not config:
        raise ImageModelNotConfiguredError(
            "未配置默认生图模型：请在「模型管理」添加模型类型为「生图」的配置并设为默认"
        )

    api_key = (config["api_key"] or "").strip() or SHENGSUANYUN_API_KEY
    if not api_key:
        raise ImageModelNotConfiguredError(
            "生图 API Key 未配置：请在「模型管理」填写 API Key，或在服务端设置环境变量 SHENGSUANYUN_API_KEY"
        )

    image_model = (config["model_id"] or "").strip()
    if not image_model:
        raise ImageModelNotConfiguredError("生图模型缺少模型 ID：请在「模型管理」填写模型 ID")

    return ImageService(
        api_key=api_key,
        base_url=(config["base_url"] or "").strip() or None,
        image_model=image_model,
    )


class ImageService:
    """图片生成服务类 - 使用胜算云 API"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, image_model: str | None = None):
        # api_key 优先取传入值，留空回退服务端环境变量 SHENGSUANYUN_API_KEY
        self._api_key = (api_key or "").strip() or SHENGSUANYUN_API_KEY
        self._base_url = base_url or SHENGSUANYUN_BASE_URL
        # 实例级默认模型（模型管理配置注入；未指定时无默认，调用时显式报错）
        self._image_model = (image_model or "").strip() or None
        # OpenAI 标准图片协议（/images/generations）同步结果的缓存 {request_id: image_url}
        self._sync_results: dict[str, str] = {}

    def _is_shengsuanyun(self) -> bool:
        """是否走盛算云 tasks 协议（非盛算云 base_url 走 OpenAI 标准图片协议）"""
        return "shengsuanyun.com" in self._base_url

    @staticmethod
    def _get_openai_image_size(video_params: "VideoParams") -> str:
        """按视频宽高比与分辨率选择 OpenAI 图片协议推荐尺寸

        依据 pucoding.com Image API 规则：宽高必须是 16 的倍数
        （例如 16:9 下 1920x1080 无效，需用 1920x1088）。
        """
        # 各宽高比下（按分辨率从低到高）的合法尺寸
        size_table = {
            "16:9": ["1280x720", "1920x1088", "2560x1440", "3840x2160"],
            "9:16": ["720x1280", "1088x1920", "1440x2560", "2160x3840"],
            "1:1": ["1024x1024", "1536x1536", "2048x2048"],
            "4:3": ["1024x768", "1280x960", "2048x1536"],
            "3:2": ["1536x1024", "1920x1280", "3072x2048"],
            "2:3": ["1024x1536", "1280x1920", "2048x3072"],
            "21:9": ["3440x1440", "3840x1600"],
        }
        sizes = size_table.get(video_params.aspect_ratio, size_table["16:9"])

        # 分辨率档位映射到尺寸档位
        res = (video_params.resolution or "720p").lower()
        level = {"720p": 0, "1080p": 1, "2k": 2, "4k": 3}.get(res, 0)
        return sizes[min(level, len(sizes) - 1)]

    def _get_size(self, resolution: str) -> str:
        """根据分辨率获取盛算云协议的尺寸参数

        支持的尺寸: 1K, 2K, 4K
        """
        size_map = {
            "720p": "1K",
            "1080p": "2K",
            "4K": "4K",
        }
        return size_map.get(resolution, "1K")

    def _compress_image(
        self,
        image_data: bytes,
        max_size: int = IMAGE_COMPRESS_MAX_SIZE,
        quality: int = IMAGE_COMPRESS_QUALITY
    ) -> tuple[bytes, str]:
        """压缩图片

        Args:
            image_data: 原始图片数据
            max_size: 最大边长（像素），超过则等比缩放
            quality: JPEG 压缩质量（1-100）

        Returns:
            (压缩后的图片数据, MIME类型)
        """
        try:
            # 打开图片
            img = Image.open(io.BytesIO(image_data))

            # 获取原始尺寸
            original_width, original_height = img.size
            original_size_kb = len(image_data) / 1024

            # 判断是否需要缩放
            need_resize = original_width > max_size or original_height > max_size

            if need_resize:
                # 计算缩放比例，保持宽高比
                ratio = min(max_size / original_width, max_size / original_height)
                new_width = int(original_width * ratio)
                new_height = int(original_height * ratio)

                # 使用高质量缩放算法
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                logger.info(f"图片已缩放: {original_width}x{original_height} -> {new_width}x{new_height}")

            # 转换为 RGB 模式（JPEG 不支持 RGBA）
            if img.mode in ('RGBA', 'P', 'LA'):
                # 创建白色背景
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # 压缩为 JPEG
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=quality, optimize=True)
            compressed_data = output.getvalue()

            compressed_size_kb = len(compressed_data) / 1024
            logger.info(f"图片压缩完成: {original_size_kb:.1f}KB -> {compressed_size_kb:.1f}KB (压缩率: {compressed_size_kb/original_size_kb*100:.1f}%)")

            return compressed_data, "image/jpeg"

        except Exception as e:
            logger.error(f"图片压缩失败: {e}")
            # 压缩失败时返回原始数据
            return image_data, "image/png"

    def _image_to_base64(
        self,
        image_path: str,
        compress: bool = False,
        max_size: int = IMAGE_COMPRESS_MAX_SIZE,
        quality: int = IMAGE_COMPRESS_QUALITY
    ) -> str | None:
        """将图片转换为 base64 格式

        Args:
            image_path: 图片路径（本地路径或URL）
            compress: 是否压缩图片（默认 False，用于首尾帧生成时设为 True）
            max_size: 压缩时的最大边长（像素）
            quality: 压缩时的 JPEG 质量（1-100）

        Returns:
            base64 编码的图片字符串，格式为 data:image/xxx;base64,xxx
        """
        try:
            # 如果是URL，需要先下载再压缩（如果需要压缩）
            if image_path.startswith(('http://', 'https://')):
                if compress:
                    # 需要压缩，先下载图片
                    import httpx
                    try:
                        with httpx.Client(timeout=30.0) as client:
                            response = client.get(image_path)
                            if response.status_code == 200:
                                image_data = response.content
                                compressed_data, mime_type = self._compress_image(image_data, max_size, quality)
                                base64_str = base64.b64encode(compressed_data).decode("utf-8")
                                return f"data:{mime_type};base64,{base64_str}"
                            else:
                                logger.warning(f"下载图片失败: HTTP {response.status_code}，使用原始URL")
                                return image_path
                    except Exception as e:
                        logger.warning(f"下载图片异常: {e}，使用原始URL")
                        return image_path
                else:
                    # 不需要压缩，直接返回URL
                    return image_path

            # 本地文件
            path = Path(image_path)
            if not path.exists():
                logger.error(f"图片文件不存在: {image_path}")
                return None

            # 读取图片数据
            with open(path, "rb") as f:
                image_data = f.read()

            if compress:
                # 压缩图片
                compressed_data, mime_type = self._compress_image(image_data, max_size, quality)
                base64_str = base64.b64encode(compressed_data).decode("utf-8")
                return f"data:{mime_type};base64,{base64_str}"
            else:
                # 不压缩，直接编码
                mime_type, _ = mimetypes.guess_type(str(path))
                if not mime_type:
                    mime_type = "image/png"
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
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(poll_url, headers=headers)

                if response.status_code != 200:
                    logger.warning(f"查询任务失败: HTTP {response.status_code}")
                    return {
                        "success": False,
                        "status": "error",
                        "error": f"HTTP {response.status_code}"
                    }

                result = response.json()
                api_code = result.get("code", "").lower()
                data = result.get("data", {})
                task_status = data.get("status", "").upper()

                logger.info(f"任务 {task_id} API状态: {api_code}, 任务状态: {task_status}")

                if api_code not in ("success", ""):
                    error_msg = result.get("error", {}).get("message", result.get("message", "API调用失败"))
                    return {
                        "success": False,
                        "status": "error",
                        "error": error_msg
                    }

                if task_status == "COMPLETED":
                    image_url = self._extract_image_url(result)
                    if image_url:
                        return {
                            "success": True,
                            "status": "completed",
                            "image_url": image_url
                        }
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
        """从结果中提取图片 URL"""
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
        timeout: int = 150,
        poll_interval: int = 3,
        model: str | None = None
    ) -> dict:
        """生成图片（文生图）- 复用统一的 submit_image_task 双协议链路

        Args:
            prompt: 图片提示词
            video_params: 视频参数
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）
            model: 使用的模型（可选，默认使用实例配置模型，未配置时报错）

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        submit_result = await self.submit_image_task(prompt, video_params, model=model)
        if not submit_result.get("success"):
            return submit_result

        return await self.poll_i2i_task(submit_result["request_id"], timeout, poll_interval)

    async def submit_image_task(
        self,
        prompt: str,
        video_params: VideoParams,
        reference_images: list[str] | None = None,
        model: str | None = None,
        compress_reference: bool = False,
    ) -> dict:
        """提交图片生成任务（只提交，不轮询）- 支持文生图和图生图

        Args:
            prompt: 图片提示词
            video_params: 视频参数
            reference_images: 参考图路径列表（可选，有则使用图生图，无则使用文生图）
            model: 使用的模型（可选，默认使用实例配置模型，未配置时报错）
            compress_reference: 是否压缩参考图（默认 False，生成首尾帧时建议设为 True）

        Returns:
            {"success": bool, "request_id": str, "error": str}
        """
        size = self._get_size(video_params.resolution)
        use_model = model or self._image_model
        if not use_model or not self._api_key:
            logger.error(_NOT_CONFIGURED_MSG)
            return {"success": False, "error": _NOT_CONFIGURED_MSG}

        # 非盛算云服务：走 OpenAI 标准图片协议（同步生成，结果缓存后由 poll 取回）
        if not self._is_shengsuanyun():
            return await self._submit_openai_image_task(
                styled_prompt=prompt, use_model=use_model,
                video_params=video_params, reference_images=reference_images,
                compress_reference=compress_reference,
            )

        # 处理参考图
        images_data = []
        if reference_images:
            for img_path in reference_images:
                img_data = self._image_to_base64(img_path, compress=compress_reference)
                if img_data:
                    images_data.append(img_data)
                else:
                    logger.warning(f"跳过无效的参考图: {img_path}")

        url = f"{self._base_url}/tasks/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = {
            "model": use_model,
            "prompt": prompt,
            "size": size,
            "aspect_ratio": video_params.aspect_ratio,
        }

        # 如果有参考图，添加到请求中
        if images_data:
            payload["images"] = images_data

        try:
            mode = "图生图" if images_data else "文生图"
            ref_info = f" (参考图: {len(images_data)}张)" if images_data else ""
            async with httpx.AsyncClient(timeout=15.0) as client:
                logger.info(f"[{mode}] 使用模型: {use_model}")
                logger.info(f"提交{mode}任务: {prompt[:50]}...{ref_info}")
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code not in (200, 201, 202):
                    logger.error(f"{mode}提交失败: HTTP {response.status_code} - {response.text}")
                    return {"success": False, "error": f"HTTP {response.status_code}"}

                result = response.json()
                logger.info(f"提交响应: {result}")

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
            logger.error(f"提交{mode}任务异常: {e}")
            return {"success": False, "error": str(e)}

    async def submit_i2i_task(
        self,
        prompt: str,
        reference_images: list[str],
        video_params: VideoParams,
        model: str | None = None,
        compress_reference: bool = False,
    ) -> dict:
        """提交图生图任务（只提交，不轮询）- 兼容旧接口

        Args:
            prompt: 图片提示词
            reference_images: 参考图路径列表（本地路径或URL）
            video_params: 视频参数
            model: 使用的模型（可选，默认使用实例配置模型，未配置时报错）
            compress_reference: 是否压缩参考图（默认 False，生成首尾帧时建议设为 True）

        Returns:
            {"success": bool, "request_id": str, "error": str}
        """
        if not reference_images:
            return {"success": False, "error": "没有有效的参考图"}
        return await self.submit_image_task(prompt, video_params, reference_images, model=model, compress_reference=compress_reference)

    async def _submit_openai_image_task(
        self,
        styled_prompt: str,
        use_model: str,
        video_params: "VideoParams",
        reference_images: list[str] | None,
        compress_reference: bool,
    ) -> dict:
        """OpenAI 标准图片协议提交（同步生成，参考 pucoding.com Image API 文档）

        文生图: POST /images/generations (JSON)
        图生图: POST /images/edits (multipart，image 字段可重复 1-4 张参考图)

        同步接口无任务ID可轮询：生成 request_id 缓存结果，
        上层 poll_i2i_task 命中缓存后直接返回。

        Returns:
            {"success": bool, "request_id": str, "error": str}
        """
        import uuid as _uuid
        request_id = f"openai-{_uuid.uuid4().hex[:12]}"

        openai_size = self._get_openai_image_size(video_params)

        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                # 部分服务存在间歇性分组路由问题（404/502），做轻量重试
                max_attempts = 3
                response = None
                for attempt in range(max_attempts):
                    if reference_images:
                        # 图生图：/images/edits multipart（image 字段可重复，最多 4 张参考图）
                        files = []
                        for ref in reference_images[:4]:
                            img_bytes, mime = await self._load_reference_bytes(ref, compress_reference)
                            if img_bytes is not None:
                                files.append(("image", ("reference.png", img_bytes, mime or "image/png")))
                        if not files:
                            return {"success": False, "error": f"参考图无法读取: {reference_images[0]}"}

                        response = await client.post(
                            f"{self._base_url}/images/edits",
                            headers=headers,
                            data={
                                "model": use_model, "prompt": styled_prompt, "size": openai_size,
                                "n": 1, "quality": "auto", "response_format": "b64_json",
                            },
                            files=files,
                        )
                    else:
                        # 文生图：/images/generations JSON
                        response = await client.post(
                            f"{self._base_url}/images/generations",
                            headers={**headers, "Content-Type": "application/json"},
                            json={
                                "model": use_model, "prompt": styled_prompt, "size": openai_size,
                                "n": 1, "quality": "auto", "response_format": "b64_json",
                            },
                        )

                    if response.status_code == 200:
                        break
                    if attempt < max_attempts - 1 and response.status_code in (404, 429, 500, 502, 503):
                        logger.warning(f"[OpenAI图片] HTTP {response.status_code}，{5 * (attempt + 1)}s 后重试 ({attempt + 2}/{max_attempts})")
                        await asyncio.sleep(5 * (attempt + 1))
                    else:
                        break

                if response.status_code != 200:
                    error_text = response.text[:300]
                    logger.error(f"[OpenAI图片] 提交失败 HTTP {response.status_code}: {error_text}")
                    return {"success": False, "error": f"HTTP {response.status_code}: {error_text}"}

                data = response.json()
                item = (data.get("data") or [{}])[0]
                image_url = item.get("url") or ""

                # b64_json 响应：落盘到 static/images/ 返回相对路径
                if not image_url and item.get("b64_json"):
                    import base64 as _b64
                    img_dir = Path("static/images")
                    img_dir.mkdir(parents=True, exist_ok=True)
                    fname = f"openai_{_uuid.uuid4().hex[:8]}.png"
                    (img_dir / fname).write_bytes(_b64.b64decode(item["b64_json"]))
                    image_url = str(img_dir / fname)

                if not image_url:
                    return {"success": False, "error": f"响应中无图片: {str(data)[:300]}"}

                # 缓存同步结果，供 poll_i2i_task 取回
                self._sync_results[request_id] = image_url
                logger.info(f"[OpenAI图片] 生成成功 [{request_id}]: {image_url[:80]}")
                return {"success": True, "request_id": request_id}

        except Exception as e:
            logger.error(f"[OpenAI图片] 提交异常: {e}")
            return {"success": False, "error": str(e)}

    async def _load_reference_bytes(self, image_path: str, compress: bool) -> tuple[bytes | None, str | None]:
        """读取参考图为字节（支持本地路径与 URL），可选压缩"""
        try:
            if image_path.startswith(("http://", "https://")):
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(image_path)
                    resp.raise_for_status()
                    data = resp.content
            else:
                path = Path(image_path)
                if not path.is_absolute():
                    root = Path(__file__).parent.parent.parent.parent
                    path = root / image_path
                if not path.exists():
                    logger.warning(f"参考图不存在: {path}")
                    return None, None
                data = path.read_bytes()

            if compress:
                data, mime = self._compress_image(data)
                return data, mime
            return data, mimetypes.guess_type(image_path)[0] or "image/png"
        except Exception as e:
            logger.error(f"读取参考图失败 {image_path}: {e}")
            return None, None

    async def poll_i2i_task(
        self,
        request_id: str,
        timeout: int = 150,
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
        # OpenAI 同步协议：命中缓存直接返回
        if request_id in self._sync_results:
            image_url = self._sync_results.pop(request_id)
            return {"success": True, "image_url": image_url}

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
        timeout: int = 150,
        poll_interval: int = 3,
        model: str | None = None,
        compress_reference: bool = False
    ) -> dict:
        """基于参考图生成图片（图生图）- 提交并等待完成

        Args:
            prompt: 图片提示词
            reference_images: 参考图URL列表
            video_params: 视频参数
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）
            model: 使用的模型（可选，默认使用实例配置模型，未配置时报错）
            compress_reference: 是否压缩参考图（默认 False，生成首尾帧时建议设为 True）

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        submit_result = await self.submit_i2i_task(prompt, reference_images, video_params, model=model, compress_reference=compress_reference)
        if not submit_result.get("success"):
            return submit_result

        request_id = submit_result["request_id"]
        return await self.poll_i2i_task(request_id, timeout, poll_interval)

    async def _generate_single_image_with_optional_reference(
        self,
        prompt: str,
        video_params: VideoParams,
        reference_images: list[str] | None = None,
        timeout: int = 150,
        poll_interval: int = 5
    ) -> dict:
        """生成单张图片（支持可选的参考图）- 复用统一的 submit_image_task 双协议链路

        统一的方法：有参考图时使用图生图，无参考图时使用文生图

        Args:
            prompt: 图片提示词
            video_params: 视频参数
            reference_images: 参考图路径列表（可选）
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        submit_result = await self.submit_image_task(prompt, video_params, reference_images)
        if not submit_result.get("success"):
            return submit_result

        return await self.poll_i2i_task(submit_result["request_id"], timeout, poll_interval)

    async def generate_material_images(
        self,
        prompts_data: list[dict],
        video_params: VideoParams,
        reference_images: list[str] | None = None
    ) -> list[MaterialImage]:
        """生成素材图片（并发间隔生成模式）

        优化策略：
        1. 间隔提交所有任务（避免服务端压力过大）
        2. 并发轮询所有任务结果（大幅提升速度）

        统一的方法：有参考图时使用图生图，无参考图时使用文生图

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
        type_names = {
            "character": "角色设定图",
            "character_main": "主要角色设定图",
            "character_minor": "边缘角色设定图",
            "props": "物品/道具设定图",
            "environment": "场景设定图",
            "environment_main": "主场景设定图",
            "environment_minor": "副场景设定图",
            "general": "素材图"
        }

        mode = "图生图" if reference_images else "文生图"
        if reference_images:
            logger.info(f"检测到 {len(reference_images)} 张参考图，使用图生图模式")

        # ========== 1. 准备任务数据 ==========
        task_items = []  # [(index, prompt, description, image_type, type_name)]
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
            styled_prompt = f"{prompt}，高质量，细节丰富，专业概念艺术设定图"

            # 如果有参考图，在提示词中说明
            if reference_images:
                styled_prompt = f"基于提供的参考图，{styled_prompt}"

            type_name = type_names.get(image_type, "素材图")
            task_items.append((i, styled_prompt, description, image_type, type_name))

        total_count = len(task_items)
        logger.info(f"[素材图生成] 开始并发间隔生成 {total_count} 张素材图（{mode}模式，间隔 {SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP} 秒）")

        # ========== 2. 间隔提交所有任务 ==========
        submitted_tasks = []  # [(index, request_id, description, image_type, styled_prompt)]

        for idx, (i, styled_prompt, description, image_type, type_name) in enumerate(task_items):
            # 间隔提交（第一个任务不需要等待）
            if idx > 0:
                await asyncio.sleep(SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP)

            logger.info(f"[素材图生成] 提交任务 {idx + 1}/{total_count}: {type_name}")

            try:
                submit_result = await self.submit_image_task(
                    styled_prompt,
                    video_params,
                    reference_images
                )

                if submit_result.get("success"):
                    request_id = submit_result["request_id"]
                    submitted_tasks.append((i, request_id, description, image_type, styled_prompt))
                    logger.info(f"[素材图生成] {type_name} 任务已提交: {request_id}")
                else:
                    logger.error(f"[素材图生成] {type_name} 提交失败: {submit_result.get('error')}")
                    submitted_tasks.append((i, None, description, image_type, styled_prompt))
            except Exception as e:
                logger.error(f"[素材图生成] {type_name} 提交异常: {e}")
                submitted_tasks.append((i, None, description, image_type, styled_prompt))

        logger.info(f"[素材图生成] 所有任务已提交，开始并发轮询 {len(submitted_tasks)} 个任务...")

        # ========== 3. 并发轮询所有任务 ==========
        async def poll_task(index: int, request_id: str | None, description: str, image_type: str, styled_prompt: str) -> MaterialImage:
            """轮询单个任务并返回 MaterialImage"""
            if not request_id:
                return MaterialImage(
                    image_id=f"error_{index}",
                    image_path="",
                    prompt=styled_prompt,
                    description=f"生成失败: 任务提交失败",
                    image_type=image_type,
                    task_id="",
                    task_status="failed"
                )

            try:
                result = await self.poll_i2i_task(request_id, timeout=180, poll_interval=5)
                if result.get("success"):
                    image_id = str(uuid.uuid4())
                    logger.info(f"[素材图生成] 任务 {request_id} 完成")
                    return MaterialImage(
                        image_id=image_id,
                        image_path=result.get("image_url", ""),
                        prompt=styled_prompt,
                        description=description,
                        image_type=image_type,
                        task_id=request_id,
                        task_status="completed"
                    )
                else:
                    logger.error(f"[素材图生成] 任务 {request_id} 失败: {result.get('error')}")
                    return MaterialImage(
                        image_id=f"error_{index}",
                        image_path="",
                        prompt=styled_prompt,
                        description=f"生成失败: {result.get('error', '未知错误')}",
                        image_type=image_type,
                        task_id=request_id,
                        task_status="failed"
                    )
            except Exception as e:
                logger.error(f"[素材图生成] 任务 {request_id} 轮询异常: {e}")
                return MaterialImage(
                    image_id=f"error_{index}",
                    image_path="",
                    prompt=styled_prompt,
                    description=f"生成失败: {str(e)}",
                    image_type=image_type,
                    task_id=request_id or "",
                    task_status="failed"
                )

        # 并发执行所有轮询
        poll_tasks = [
            poll_task(i, request_id, description, image_type, styled_prompt)
            for i, request_id, description, image_type, styled_prompt in submitted_tasks
        ]
        results = await asyncio.gather(*poll_tasks)

        # 统计结果
        success_count = sum(1 for r in results if r.task_status == "completed")
        failed_count = len(results) - success_count
        logger.info(f"[素材图生成] 完成！成功: {success_count} 张，失败: {failed_count} 张")

        return list(results)

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
        styled_prompt = f"{prompt}，高质量"

        frame_context = ""
        if frame_type == "first":
            frame_context = (
                "这是视频片段的首帧（开场镜头），"
                "捕捉动作开始时的状态。"
            )
        elif frame_type == "last":
            frame_context = (
                "这是视频片段的尾帧（结束镜头），"
                "捕捉动作完成后的最终状态。"
            )

        i2i_prompt = (
            f"{frame_context}"
            f"基于参考图生成完整的一帧视频{frame_type == 'first' and '开场' or '结束'}画面：{styled_prompt}。"
            f"保持与参考图中相同的角色、物品和视觉风格。"
            f"重要提示：不要包含任何标注、标签、文字、身高比例尺、尺寸标注；人物和道具必须与参考图保持一致。"
            f"比例尺、尺寸标记或设计参考图元素。"
            f"生成一个适合视频制作的干净电影画面，而不是设计稿。"
        )
        return i2i_prompt   

    async def generate_single_image(
        self,
        prompt: str,
        video_params: VideoParams,
        prefix: str = "",
        reference_images: list[str] | None = None,
        frame_type: str = "",
        model: str | None = None,
        compress_reference: bool = False,
    ) -> tuple[str, str]:
        """生成单张图片（支持图生图）

        Args:
            prompt: 图片提示词
            video_params: 视频参数
            prefix: 图片标识前缀（用于日志）
            reference_images: 参考图URL列表（素材图），用于保持角色/物品一致性
            frame_type: 帧类型，"first" 表示首帧，"last" 表示尾帧
            model: 使用的模型（可选，默认使用实例配置模型，未配置时报错）
            compress_reference: 是否压缩参考图（默认 False，生成首尾帧时建议设为 True）

        Returns:
            (image_id, image_url)
        """
        styled_prompt = f"{prompt}，高质量"
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
                    video_params,
                    model=model,
                    compress_reference=compress_reference
                )
            else:
                result = await self._generate_image(styled_prompt, video_params)

            if result.get("success"):
                return image_id, result.get("image_url", "")

        except Exception as e:
            logger.error(f"生成图片失败: {e}")

        return "error", ""

    async def edit_material_image(
        self,
        original_image_path: str,
        prompt: str,
        video_params: VideoParams,
        reference_images: list[str] | None = None,
        timeout: int = 180,
        poll_interval: int = 5
    ) -> dict:
        """编辑单个素材图（图生图）

        Args:
            original_image_path: 原始素材图路径（本地路径或URL）
            prompt: 完整提示词
            video_params: 视频参数
            reference_images: 用户选择的参考图路径列表（可选）
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        logger.info(f"[素材图编辑] 开始编辑素材图: {prompt[:50]}...")

        # 确定最终使用的参考图列表
        if reference_images and len(reference_images) > 0:
            all_reference_images = reference_images
            logger.info(f"[素材图编辑] 使用用户选择的 {len(reference_images)} 张参考图")
        else:
            all_reference_images = [original_image_path]
            logger.info(f"[素材图编辑] 用户未选择参考图，使用原素材图作为保底")

        logger.info(f"[素材图编辑] 总共需要处理 {len(all_reference_images)} 张参考图")

        # 使用统一的图生图方法
        result = await self._generate_single_image_with_optional_reference(
            prompt=prompt,
            video_params=video_params,
            reference_images=all_reference_images,
            timeout=timeout,
            poll_interval=poll_interval
        )

        if result.get("success"):
            logger.info(f"[素材图编辑] 编辑成功，新图URL: {result.get('image_url')}")
        else:
            logger.error(f"[素材图编辑] 编辑失败: {result.get('error')}")

        return result
