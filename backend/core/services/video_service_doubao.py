"""视频生成服务 - 使用豆包 doubao-seedance-1.0-pro 模型 (盛算云 API)"""
import uuid
import asyncio
import httpx
import base64
import mimetypes
from pathlib import Path
from PIL import Image
import io

from backend.core.config import (
    SHENGSUANYUN_API_KEY, SHENGSUANYUN_BASE_URL, SHENGSUANYUN_VIDEO_MODEL_DOUBAO,
)
from backend.core.models import GeneratedVideo, ScriptSegment, VideoParams

# 视频保存目录
VIDEO_SAVE_DIR = Path("static/videos")

# 图片压缩配置
IMAGE_COMPRESS_MAX_SIZE = 1024  # 压缩后的最大边长（像素）
IMAGE_COMPRESS_QUALITY = 85     # JPEG 压缩质量（1-100）


class VideoServiceDoubao:
    """视频生成服务类 - 使用豆包 doubao-seedance-1.0-pro 首尾帧模型"""

    def __init__(self, api_key: str = SHENGSUANYUN_API_KEY):
        self.api_key = api_key
        self.base_url = SHENGSUANYUN_BASE_URL
        self.model = SHENGSUANYUN_VIDEO_MODEL_DOUBAO

    def _get_resolution(self, resolution: str) -> str:
        """转换分辨率格式（doubao-seedance 支持 720p, 1080p, 2k, 4k）"""
        if "4k" in resolution.lower():
            return "4k"
        elif "2k" in resolution.lower():
            return "2k"
        elif "1080" in resolution.lower():
            return "1080p"
        return "720p"

    def _get_duration(self, segment_duration: float) -> int:
        """获取视频时长（doubao-seedance 支持 5 秒或 10 秒）"""
        # 根据分片时长选择合适的视频时长
        if segment_duration >= 8:
            return 10
        else:
            return 5

    def _get_ratio(self, aspect_ratio: str) -> str:
        """转换宽高比格式"""
        ratio_map = {
            "16:9": "16:9",
            "9:16": "9:16",
            "1:1": "1:1",
            "3:4": "3:4",
            "4:3": "4:3",
            "21:9": "21:9",
        }
        return ratio_map.get(aspect_ratio, "adaptive")

    def _get_fps(self, duration: int) -> int:
        """获取帧率（doubao-seedance 支持 16 或 24 fps）"""
        # 通常 24fps 更流畅，但可以根据需要调整
        return 24

    def _compress_image(self, image_data: bytes, max_size: int = IMAGE_COMPRESS_MAX_SIZE, quality: int = IMAGE_COMPRESS_QUALITY) -> tuple[bytes, str]:
        """压缩图片到指定大小

        Args:
            image_data: 原始图片数据
            max_size: 压缩后的最大边长（像素）
            quality: JPEG 压缩质量（1-100）

        Returns:
            (压缩后的图片数据, MIME类型)
        """
        try:
            # 从字节数据创建 PIL Image
            image = Image.open(io.BytesIO(image_data))

            # 转换为 RGB（处理 RGBA 或调色板模式）
            if image.mode in ('RGBA', 'LA', 'P'):
                # 对于带透明通道的图片，使用白色背景
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                if image.mode in ('RGBA', 'LA'):
                    background.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
                    image = background
                else:
                    image = image.convert('RGB')
            elif image.mode != 'RGB':
                image = image.convert('RGB')

            # 计算缩放比例
            width, height = image.size
            max_dim = max(width, height)

            if max_dim > max_size:
                scale = max_size / max_dim
                new_width = int(width * scale)
                new_height = int(height * scale)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # 保存为 JPEG 并压缩
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=quality, optimize=True)
            output.seek(0)

            return output.read(), 'image/jpeg'

        except Exception as e:
            print(f"图片压缩失败: {e}")
            # 压缩失败时返回原始数据
            return image_data, "image/png"

    def _image_to_base64(self, image_path: str, compress: bool = True) -> str | None:
        """将图片转换为 base64 格式

        Args:
            image_path: 图片路径（本地路径或URL）
            compress: 是否压缩图片（默认 True）

        Returns:
            base64 编码的图片字符串，格式为 data:image/xxx;base64,xxx
            如果是URL且不需要压缩，则直接返回URL
        """
        try:
            # 如果是URL，直接返回（不压缩）
            if image_path.startswith(('http://', 'https://')):
                return image_path

            # 本地文件
            path = Path(image_path)
            if not path.exists():
                print(f"图片文件不存在: {image_path}")
                return None

            # 读取图片数据
            with open(path, "rb") as f:
                image_data = f.read()

            if compress:
                # 压缩图片
                compressed_data, mime_type = self._compress_image(image_data, IMAGE_COMPRESS_MAX_SIZE, IMAGE_COMPRESS_QUALITY)
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
            print(f"转换图片为 base64 失败: {e}")
            return None

    async def _download_video(self, video_url: str, segment_index: int, video_id: str) -> str:
        """下载视频并以分片索引命名

        Args:
            video_url: 视频URL
            segment_index: 分片索引（从0开始）
            video_id: 视频ID（用于生成唯一文件名）

        Returns:
            本地文件路径
        """
        # 确保目录存在
        VIDEO_SAVE_DIR.mkdir(parents=True, exist_ok=True)

        # 生成文件名：分片_{索引+1}_{短ID}.mp4
        short_id = video_id[:8]
        filename = f"分片{segment_index + 1:02d}_{short_id}.mp4"
        local_path = VIDEO_SAVE_DIR / filename

        try:
            async with httpx.AsyncClient(timeout=150.0) as client:
                response = await client.get(video_url)
                response.raise_for_status()

                with open(local_path, "wb") as f:
                    f.write(response.content)

                print(f"视频已下载: {local_path}")
                return str(local_path)

        except Exception as e:
            print(f"下载视频失败: {e}")
            # 下载失败时返回原始URL
            return video_url

    async def _submit_video_task(
        self,
        prompt: str,
        first_frame_url: str | None = None,
        last_frame_url: str | None = None,
        resolution: str = "720p",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        reference_images: list[str] | None = None,
    ) -> str:
        """提交视频生成任务，返回 task_id

        Args:
            prompt: 视频提示词
            first_frame_url: 首帧图片URL或本地路径
            last_frame_url: 尾帧图片URL或本地路径
            resolution: 分辨率（720p, 1080p, 2k, 4k）
            duration: 视频时长（5 或 10 秒）
            aspect_ratio: 宽高比（16:9, 9:16, 1:1, 3:4, 4:3, 21:9）
            reference_images: 参考图URL列表或本地路径列表（用于首帧+参考图模式）
        """
        if not self.api_key:
            raise ValueError("视频服务 API Key 未配置：请在服务端设置环境变量 SHENGSUANYUN_API_KEY")

        url = f"{self.base_url}/tasks/generations"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "prompt": prompt,
            "resolution": resolution,
            "duration": duration,
            "ratio": self._get_ratio(aspect_ratio),
            "fps": self._get_fps(duration),
        }

        # 豆包首尾帧控制：使用 image 和 image_tail
        # 如果是本地路径，转换为 base64（压缩）
        if first_frame_url:
            first_frame_data = self._image_to_base64(first_frame_url, compress=True)
            if first_frame_data:
                payload["image"] = first_frame_data
                payload["image_role"] = "first_frame"
                print(f"[视频任务] 首帧已转换: {first_frame_url[:50]}... -> base64 ({len(first_frame_data)} 字符)")

        if last_frame_url and first_frame_url:
            last_frame_data = self._image_to_base64(last_frame_url, compress=True)
            if last_frame_data:
                payload["image_tail"] = last_frame_data
                payload["image_tail_role"] = "last_frame"
                print(f"[视频任务] 尾帧已转换: {last_frame_url[:50]}... -> base64 ({len(last_frame_data)} 字符)")

        # 添加参考图（用于首帧+参考图模式）
        # 注意：参考图会作为视觉参考，但不像尾帧那样强制结束画面
        if reference_images and len(reference_images) > 0:
            # 最多使用3张参考图，将本地路径转换为 base64
            refs = []
            for img_path in reference_images[:3]:
                img_data = self._image_to_base64(img_path, compress=True)
                if img_data:
                    refs.append(img_data)
                    print(f"[视频任务] 参考图已转换: {img_path[:50]}... -> base64 ({len(img_data)} 字符)")
                else:
                    # 转换失败，如果是URL则直接使用
                    if img_path.startswith(('http://', 'https://')):
                        refs.append(img_path)
            if refs:
                payload["reference_images"] = refs

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            # 提取 task_id
            data = result.get("data", {})
            task_id = data.get("task_id") or data.get("request_id") or result.get("request_id")
            if task_id:
                return task_id
            else:
                raise ValueError(f"提交任务失败: {result}")

    async def _get_task_status(self, task_id: str) -> dict:
        """查询任务状态"""
        url = f"{self.base_url}/tasks/generations/{task_id}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def _wait_for_task(self, task_id: str, max_wait: int = 600) -> dict:
        """等待任务完成

        根据API文档，任务状态包括:
        - SUBMITTING: 提交中
        - SUBMITTED: 已提交
        - IN_PROGRESS: 处理中
        - COMPLETED: 已完成
        - FAILED: 失败
        - CANCELLED: 已取消
        """
        elapsed = 0
        interval = 10

        while elapsed < max_wait:
            result = await self._get_task_status(task_id)

            # 提取状态信息
            data = result.get("data", {})
            status = data.get("status", "").upper()

            if status == "COMPLETED":
                return result
            elif status in ["FAILED", "CANCELLED"]:
                fail_reason = data.get("fail_reason") or result.get("message") or "任务失败"
                raise ValueError(f"视频生成失败: {fail_reason}")
            elif status in ["SUBMITTING", "SUBMITTED", "IN_PROGRESS"]:
                progress = data.get("progress", "0%")
                print(f"视频生成中(doubao-seedance)... 状态: {status}, 进度: {progress}")
                await asyncio.sleep(interval)
                elapsed += interval
            else:
                # 未知状态，继续等待
                await asyncio.sleep(interval)
                elapsed += interval

        raise TimeoutError(f"任务超时: task_id={task_id}")

    async def generate_video_from_frames(
        self,
        segment: ScriptSegment,
        first_image_url: str,
        last_image_url: str,
        video_params: VideoParams,
        total_segments: int = 1,
        extra_prompt: str = "",
        prev_segment: ScriptSegment | None = None,
        next_segment: ScriptSegment | None = None,
    ) -> GeneratedVideo:
        """基于参考图片生成视频

        Args:
            segment: 分片脚本
            first_image_url: 首帧图片URL
            last_image_url: 尾帧图片URL
            video_params: 视频参数
            total_segments: 总分片数
            extra_prompt: 额外的提示词，用于增加控制力
            prev_segment: 上一个分片脚本（用于上下文连贯）
            next_segment: 下一个分片脚本（用于上下文连贯）
        """
        # 构建视频提示词
        video_prompt = self._build_video_prompt(
            segment, video_params, total_segments, extra_prompt, prev_segment, next_segment
        )
        duration = self._get_duration(segment.duration)
        resolution = self._get_resolution(video_params.resolution)

        try:
            # 使用 doubao-seedance 首尾帧控制功能
            task_id = await self._submit_video_task(
                prompt=video_prompt,
                first_frame_url=first_image_url if first_image_url else None,
                last_frame_url=last_image_url if last_image_url else None,
                resolution=resolution,
                duration=duration,
                aspect_ratio=video_params.aspect_ratio,
            )
            print(f"【视频任务已提交-doubao-seedance首尾帧】 (分片 {segment.index}): task_id={task_id}, duration={duration}s, resolution={resolution}, ratio={video_params.aspect_ratio}")

            # 等待任务完成
            result = await self._wait_for_task(task_id)

            # 提取视频URL
            video_url = self._extract_video_url(result)

            if not video_url:
                raise ValueError("未获取到视频 URL")

            video_id = str(uuid.uuid4())

            # 下载视频并以分片索引命名
            local_path = await self._download_video(video_url, segment.index, video_id)

            return GeneratedVideo(
                segment_index=segment.index,
                video_id=video_id,
                video_path=local_path,
                duration=duration,
                prompt=video_prompt,
                task_status="completed"  # 明确设置为完成状态
            )

        except Exception as e:
            print(f"--生成视频失败 (分片 {segment.index}): {e}")
            return GeneratedVideo(
                segment_index=segment.index,
                video_id=f"error_{segment.index}",
                video_path="",
                duration=0,
                prompt=f"生成失败: {str(e)}",
                task_status="failed"  # 明确设置为失败状态
            )

    async def generate_video_from_first_frame(
        self,
        segment: ScriptSegment,
        first_image_url: str,
        video_params: VideoParams,
        reference_images: list[str] | None = None,
        total_segments: int = 1,
        extra_prompt: str = "",
        prev_segment: ScriptSegment | None = None,
        next_segment: ScriptSegment | None = None,
    ) -> GeneratedVideo:
        """基于首帧+参考图生成视频（首帧+参考图模式）

        使用豆包seedance-pro模型，基于首帧图片+参考图+提示词生成视频。
        这种模式给予模型更多的自由度，不受尾帧约束。

        Args:
            segment: 分片脚本
            first_image_url: 首帧图片URL（必需）
            video_params: 视频参数
            reference_images: 参考图URL列表（可选，通常是素材图）
            total_segments: 总分片数
            extra_prompt: 额外的提示词
            prev_segment: 上一个分片脚本（用于上下文连贯）
            next_segment: 下一个分片脚本（用于上下文连贯）
        """
        # 构建视频提示词
        video_prompt = self._build_video_prompt(
            segment, video_params, total_segments, extra_prompt, prev_segment, next_segment
        )
        duration = self._get_duration(segment.duration)
        resolution = self._get_resolution(video_params.resolution)

        try:
            # 使用 doubao-seedance 首帧+参考图模式
            task_id = await self._submit_video_task(
                prompt=video_prompt,
                first_frame_url=first_image_url if first_image_url else None,
                last_frame_url=None,  # 不传尾帧，让模型自由发挥
                resolution=resolution,
                duration=duration,
                aspect_ratio=video_params.aspect_ratio,
                reference_images=reference_images,
            )
            print(f"【视频任务已提交-doubao-seedance首帧+参考图】 (分片 {segment.index}): task_id={task_id}, duration={duration}s, resolution={resolution}, ratio={video_params.aspect_ratio}, refs={len(reference_images) if reference_images else 0}")

            # 等待任务完成
            result = await self._wait_for_task(task_id)

            # 提取视频URL
            video_url = self._extract_video_url(result)

            if not video_url:
                raise ValueError("未获取到视频 URL")

            video_id = str(uuid.uuid4())

            # 下载视频并以分片索引命名
            local_path = await self._download_video(video_url, segment.index, video_id)

            return GeneratedVideo(
                segment_index=segment.index,
                video_id=video_id,
                video_path=local_path,
                duration=duration,
                prompt=video_prompt,
                task_status="completed"
            )

        except Exception as e:
            print(f"--生成视频失败 (分片 {segment.index}): {e}")
            return GeneratedVideo(
                segment_index=segment.index,
                video_id=f"error_{segment.index}",
                video_path="",
                duration=0,
                prompt=f"生成失败: {str(e)}",
                task_status="failed"
            )

    def _build_video_prompt(
        self,
        segment: ScriptSegment,
        video_params: VideoParams,
        total_segments: int = 1,
        extra_prompt: str = "",
        prev_segment: ScriptSegment | None = None,
        next_segment: ScriptSegment | None = None,
    ) -> str:
        """构建简化的视频提示词

        只包含必要的信息：
        1. 视频总参数（风格、比例等）
        2. 当前分片的脚本内容
        3. 上一个/下一个分片的简要描述（用于上下文连贯）

        Args:
            segment: 分片脚本
            video_params: 视频参数
            total_segments: 总分片数
            extra_prompt: 额外的提示词
            prev_segment: 上一个分片脚本（用于上下文连贯）
            next_segment: 下一个分片脚本（用于上下文连贯）
        """
        parts = []

        # 1. 分片位置信息
        parts.append(f"[分片 {segment.index + 1}/{total_segments}]")

        # 2. 上一个分片的简要描述（用于过渡连贯）
        if prev_segment:
            prev_summary = prev_segment.content[:100] + "..." if len(prev_segment.content) > 100 else prev_segment.content
            parts.append(f"[前一镜头]: {prev_summary}")

        # 3. 当前分片核心内容（使用模型自带的方法）
        parts.append(f"\n[当前镜头]{segment.to_video_prompt()}")

        # 4. 下一个分片的简要描述（用于过渡连贯）
        if next_segment:
            next_summary = next_segment.content[:100] + "..." if len(next_segment.content) > 100 else next_segment.content
            parts.append(f"[后一镜头]: {next_summary}")

        # 5. 用户自定义提示词
        if extra_prompt:
            parts.append(extra_prompt)

        return "，".join(parts)

    def _extract_video_url(self, result: dict) -> str | None:
        """从API响应中提取视频URL

        根据API文档，视频URL在 data.data.video_urls 数组中
        """
        # 优先尝试文档中的标准路径: data.data.video_urls
        data = result.get("data", {})
        inner_data = data.get("data", {})
        video_urls = inner_data.get("video_urls", [])
        if video_urls:
            return video_urls[0]

        # 兼容其他可能的路径
        if data.get("video_urls"):
            return data["video_urls"][0]

        # 旧版兼容
        video_url = result.get("video_url") or data.get("video_url")
        if video_url:
            return video_url

        videos = result.get("videos") or data.get("videos", [])
        if videos:
            return videos[0].get("url") or videos[0].get("video_url")

        return None