"""图片生成服务 - 使用 OpenAI 标准图片协议生成图片"""
import asyncio
from pathlib import Path

import httpx

from backend.core.models import VideoParams
from backend.core.utils.image_utils import load_image_bytes

import logging
logger = logging.getLogger(__name__)

# 图片压缩配置
IMAGE_COMPRESS_MAX_SIZE = 1920  # 最大边长（像素）
IMAGE_COMPRESS_QUALITY = 85    # JPEG 压缩质量（1-100）

# 生图模型未配置的统一报错文案
_NOT_CONFIGURED_MSG = "生图模型未配置（缺少 API Key / Base URL / 模型 ID），请在「模型管理」完成配置"


class ImageModelNotConfiguredError(RuntimeError):
    """生图模型未配置（无默认 image 模型 / 缺 API Key / 缺模型 ID）"""


def build_image_service_from_model_config(model_config_id: str | None = None) -> "ImageService":
    """唯一的生图服务工厂：按「模型管理」配置构造 ImageService，未配置或不完整时显式报错

    Args:
        model_config_id: 模型配置ID；为 None 时读取默认生图模型配置

    Returns:
        配置好的 ImageService

    Raises:
        ImageModelNotConfiguredError: 无配置 / 配置不存在 / 缺 API Key / 缺模型 ID
    """
    from backend.core.persistence import ModelManager

    manager = ModelManager()
    if model_config_id:
        config = manager.get_model(model_config_id)
        if not config:
            raise ImageModelNotConfiguredError(f"生图模型配置不存在: {model_config_id}")
        if not config.get("enabled", True):
            raise ImageModelNotConfiguredError(f"生图模型「{config['name']}」已停用，请在「模型管理」启用后重试")
    else:
        config = manager.get_default_model(model_type="image")

    if not config:
        raise ImageModelNotConfiguredError(
            "未配置默认生图模型：请在「模型管理」添加模型类型为「生图」的配置并设为默认（已停用的模型不生效）"
        )

    api_key = (config["api_key"] or "").strip()
    if not api_key:
        raise ImageModelNotConfiguredError(
            "生图 API Key 未配置：请在「模型管理」填写 API Key"
        )

    base_url = (config["base_url"] or "").strip()
    if not base_url:
        raise ImageModelNotConfiguredError("生图模型缺少 Base URL：请在「模型管理」填写 Base URL")

    image_model = (config["model_id"] or "").strip()
    if not image_model:
        raise ImageModelNotConfiguredError("生图模型缺少模型 ID：请在「模型管理」填写模型 ID")

    return ImageService(
        api_key=api_key,
        base_url=base_url,
        image_model=image_model,
    )


class ImageService:
    """图片生成服务类 - 使用 OpenAI 标准图片协议"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, image_model: str | None = None):
        self._api_key = (api_key or "").strip()
        self._base_url = (base_url or "").rstrip("/")
        # 实例级默认模型（模型管理配置注入；未指定时无默认，调用时显式报错）
        self._image_model = (image_model or "").strip() or None
        # OpenAI 标准图片协议（/images/generations）同步结果的缓存 {request_id: image_url}
        self._sync_results: dict[str, str] = {}

    @staticmethod
    def _get_openai_image_size(video_params: "VideoParams") -> str:
        """按视频宽高比与分辨率选择 OpenAI 图片协议推荐尺寸

        依据 pucoding.com Image API 规则：宽高必须是 16 的倍数
        （例如 16:9 下 1920x1080 无效，需用 1920x1088）。
        """
        # 各宽高比下（按分辨率从低到高）的合法尺寸
        size_table = {
            "16:9": ["864x480", "1280x720", "1920x1088", "2560x1440", "3840x2160"],
            "9:16": ["480x864", "720x1280", "1088x1920", "1440x2560", "2160x3840"],
            "1:1": ["768x768", "1024x1024", "1536x1536", "2048x2048"],
            "4:3": ["768x576", "1024x768", "1280x960", "2048x1536"],
            "3:2": ["768x512", "1536x1024", "1920x1280", "3072x2048"],
            "2:3": ["512x768", "1024x1536", "1280x1920", "2048x3072"],
            "21:9": ["1120x480", "3440x1440", "3840x1600"],
        }
        sizes = size_table.get(video_params.aspect_ratio, size_table["16:9"])

        # 分辨率档位映射到尺寸档位
        res = (video_params.resolution or "720p").lower()
        level = {"480p": 0, "720p": 1, "1080p": 2, "2k": 3, "4k": 4}.get(res, 1)
        return sizes[min(level, len(sizes) - 1)]

    async def submit_image_task(
        self,
        prompt: str,
        video_params: VideoParams,
        reference_images: list[str] | None = None,
        model: str | None = None,
        compress_reference: bool = False,
    ) -> dict:
        """提交图片生成任务（只提交，不取回）- 支持文生图和图生图

        Args:
            prompt: 图片提示词
            video_params: 视频参数
            reference_images: 参考图路径列表（可选，有则使用图生图，无则使用文生图）
            model: 使用的模型（可选，默认使用实例配置模型，未配置时报错）
            compress_reference: 是否压缩参考图

        Returns:
            {"success": bool, "request_id": str, "error": str}
        """
        use_model = model or self._image_model
        if not use_model or not self._api_key or not self._base_url:
            logger.error(_NOT_CONFIGURED_MSG)
            return {"success": False, "error": _NOT_CONFIGURED_MSG}

        # OpenAI 标准图片协议（同步生成，结果缓存后由 poll 取回）
        return await self._submit_openai_image_task(
            styled_prompt=prompt, use_model=use_model,
            video_params=video_params, reference_images=reference_images,
            compress_reference=compress_reference,
        )

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
                            img_bytes, mime = await load_image_bytes(
                                ref, compress_reference,
                                max_size=IMAGE_COMPRESS_MAX_SIZE, quality=IMAGE_COMPRESS_QUALITY,
                            )
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
                    def _persist_b64() -> str:
                        import base64 as _b64
                        img_dir = Path("static/images")
                        img_dir.mkdir(parents=True, exist_ok=True)
                        fname = f"openai_{_uuid.uuid4().hex[:8]}.png"
                        (img_dir / fname).write_bytes(_b64.b64decode(item["b64_json"]))
                        return str(img_dir / fname)
                    # b64 解码 + 落盘（多 MB 图几十 ms）挪线程池防阻塞事件循环
                    image_url = await asyncio.to_thread(_persist_b64)

                if not image_url:
                    return {"success": False, "error": f"响应中无图片: {str(data)[:300]}"}

                # 缓存同步结果，供 poll_i2i_task 取回
                self._sync_results[request_id] = image_url
                logger.info(f"[OpenAI图片] 生成成功 [{request_id}]: {image_url[:80]}")
                return {"success": True, "request_id": request_id}

        except Exception as e:
            logger.error(f"[OpenAI图片] 提交异常: {e}")
            return {"success": False, "error": str(e)}

    async def poll_i2i_task(
        self,
        request_id: str,
        timeout: int = 150,
        poll_interval: int = 3
    ) -> dict:
        """取回图片任务结果（OpenAI 协议为同步生成，submit 时已缓存结果）

        Args:
            request_id: 任务ID
            timeout: 未使用（保留签名兼容调用方）
            poll_interval: 未使用（保留签名兼容调用方）

        Returns:
            {"success": bool, "image_url": str, "error": str}
        """
        if request_id in self._sync_results:
            image_url = self._sync_results.pop(request_id)
            logger.info(f"图片生成完成 [{request_id}]，图片URL: {image_url[:80]}")
            return {"success": True, "image_url": image_url}

        logger.error(f"任务结果不存在 [{request_id}]（可能已被取回或提交失败）")
        return {"success": False, "error": "任务结果不存在"}
