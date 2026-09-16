"""
即梦 v40 图生图模式备份代码

此文件包含从 image_service.py 中移除的 bytedance/jimeng_v40 图生图相关代码。
如需恢复，可将这些方法添加回 ImageService 类中。

配置项（需添加到 config.py）：
SHENGSUANYUN_MATERIAL_EDIT_MODEL = "bytedance/jimeng_v40"  # 素材图编辑模型（即梦v40图生图）

导入项（需添加到 image_service.py）：
from backend.core.config import SHENGSUANYUN_MATERIAL_EDIT_MODEL
"""

import httpx
import logging

logger = logging.getLogger(__name__)


class JimengV40ImageServiceMixin:
    """即梦 v40 图生图功能混入类

    使用方法：
    1. 在 config.py 中添加 SHENGSUANYUN_MATERIAL_EDIT_MODEL = "bytedance/jimeng_v40"
    2. 在 ImageService 类中继承此混入类或将方法复制过去
    """

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
        对于外部URL，验证其可访问性；如果不可访问，尝试下载后上传到OSS。

        Args:
            image_paths: 图片路径列表（可能是URL或本地路径）

        Returns:
            URL列表
        """
        from backend.core.services.oss_service import get_oss_service, OSSService
        from backend.core.config import OSS_ACCESS_KEY, OSS_BUCKET, OSS_ENDPOINT
        import os
        import tempfile
        import httpx

        urls = []

        for img_path in image_paths:
            if not img_path:
                continue

            # 如果已经是URL，验证其可访问性
            if img_path.startswith(('http://', 'https://')):
                # 首先检查是否是当前配置的OSS URL（私有Bucket的情况）
                oss_key = self._extract_oss_key_from_url(img_path)
                if oss_key and OSS_ACCESS_KEY and OSS_BUCKET:
                    # 是本OSS的URL，直接生成预签名URL
                    try:
                        oss_service = get_oss_service()
                        presigned_url = oss_service.get_presigned_url(oss_key, expires=3600)
                        if presigned_url:
                            urls.append(presigned_url)
                            logger.info(f"[即梦v40] OSS URL已转为预签名URL: {img_path[:60]}...")
                            continue
                    except Exception as e:
                        logger.warning(f"[即梦v40] 生成预签名URL失败: {e}")

                # 检查URL是否可访问
                is_accessible = await self._check_url_accessible(img_path)
                if is_accessible:
                    urls.append(img_path)
                    logger.info(f"[即梦v40] 使用现有可访问URL: {img_path[:80]}...")
                    continue
                else:
                    # URL不可访问，尝试下载并重新上传
                    logger.warning(f"[即梦v40] URL不可访问，尝试下载后重新上传: {img_path[:80]}...")
                    if OSS_ACCESS_KEY and OSS_BUCKET:
                        try:
                            new_url = await self._download_and_upload_image(img_path)
                            if new_url:
                                urls.append(new_url)
                                logger.info(f"[即梦v40] URL已重新上传: {new_url[:80]}...")
                                continue
                        except Exception as e:
                            logger.error(f"[即梦v40] 下载并上传图片失败: {e}")
                    # 如果无法重新上传，仍然保留原URL（让API端处理错误）
                    logger.warning(f"[即梦v40] 无法重新上传，仍尝试使用原URL")
                    urls.append(img_path)
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

    def _extract_oss_key_from_url(self, url: str) -> str | None:
        """从URL中提取OSS对象key

        检查URL是否属于当前配置的OSS，如果是则返回对象key。

        Args:
            url: 图片URL

        Returns:
            OSS对象key，如果不是当前OSS的URL则返回None
        """
        from backend.core.config import OSS_BUCKET, OSS_ENDPOINT

        if not OSS_BUCKET or not OSS_ENDPOINT:
            return None

        try:
            # 解析Endpoint主机名
            endpoint_host = OSS_ENDPOINT.replace('http://', '').replace('https://', '').rstrip('/')

            # 检查URL是否匹配当前OSS的格式
            # 格式1: https://{bucket}.{endpoint}/{key}
            expected_prefix = f"https://{OSS_BUCKET}.{endpoint_host}/"
            if url.startswith(expected_prefix):
                return url[len(expected_prefix):]

            # 格式2: http://{bucket}.{endpoint}/{key}
            expected_prefix_http = f"http://{OSS_BUCKET}.{endpoint_host}/"
            if url.startswith(expected_prefix_http):
                return url[len(expected_prefix_http):]

            return None
        except Exception:
            return None

    async def _check_url_accessible(self, url: str, timeout: int = 10) -> bool:
        """检查URL是否可访问

        Args:
            url: 要检查的URL
            timeout: 超时时间（秒）

        Returns:
            是否可访问
        """
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                # 先尝试HEAD请求
                response = await client.head(url)
                if response.status_code == 200:
                    return True
                # 某些服务器可能不支持HEAD，尝试GET
                if response.status_code in (405, 403):
                    response = await client.get(url)
                    return response.status_code == 200
                return False
        except Exception as e:
            logger.debug(f"[即梦v40] URL访问检查失败 {url[:60]}...: {e}")
            return False

    async def _download_and_upload_image(self, image_url: str) -> str | None:
        """下载图片并上传到OSS

        Args:
            image_url: 图片URL

        Returns:
            新的OSS URL，失败则返回None
        """
        from backend.core.services.oss_service import get_oss_service
        import tempfile
        import os

        try:
            # 下载图片
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(image_url)
                if response.status_code != 200:
                    logger.warning(f"[即梦v40] 下载图片失败，状态码: {response.status_code}")
                    return None

                # 获取内容类型
                content_type = response.headers.get('Content-Type', 'image/png')
                ext = '.png' if 'png' in content_type else '.jpg'

                # 保存到临时文件
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
                    tmp_file.write(response.content)
                    tmp_path = tmp_file.name

            try:
                # 上传到OSS
                oss_service = get_oss_service()
                new_url = await oss_service.upload_file(
                    local_path=tmp_path,
                    remote_dir="material_edit_temp",
                    content_type=content_type
                )
                return new_url
            finally:
                # 清理临时文件
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"[即梦v40] 下载并上传图片失败: {e}")
            return None

    async def _generate_image_with_jimeng_v40_i2i(
        self,
        prompt: str,
        image_urls: list[str],
        video_params,  # VideoParams
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
        from backend.core.config import SHENGSUANYUN_MATERIAL_EDIT_MODEL

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
