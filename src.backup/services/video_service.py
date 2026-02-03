"""视频生成服务 - 使用胜算云 API"""
import uuid
import asyncio
import httpx
from pathlib import Path

from src.config import (
    SHENGSUANYUN_API_KEY, SHENGSUANYUN_BASE_URL, SHENGSUANYUN_VIDEO_MODEL,
)
from src.models import GeneratedVideo, ScriptSegment, VideoParams

# 视频保存目录
VIDEO_SAVE_DIR = Path("static/videos")


class VideoService:
    """视频生成服务类 - 使用胜算云 API"""

    def __init__(self, api_key: str = SHENGSUANYUN_API_KEY):
        self.api_key = api_key
        self.base_url = SHENGSUANYUN_BASE_URL
        self.model = SHENGSUANYUN_VIDEO_MODEL

    def _get_aspect_ratio(self, aspect_ratio: str) -> str:
        """转换宽高比格式（即梦支持 16:9, 4:3, 1:1, 3:4, 9:16, 21:9）"""
        supported = {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9"}
        return aspect_ratio if aspect_ratio in supported else "16:9"

    def _get_frames(self, segment_duration: float) -> int:
        """获取视频帧数（即梦：121=5秒，241=10秒）"""
        # 帧数 = 24 * n + 1，其中 n 为秒数
        if segment_duration >= 8:
            return 241  # 10秒
        else:
            return 121  # 5秒

    def _get_duration_from_frames(self, frames: int) -> int:
        """从帧数计算时长"""
        return 10 if frames == 241 else 5

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
            async with httpx.AsyncClient(timeout=120.0) as client:
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
        aspect_ratio: str = "16:9",
        frames: int = 121,
    ) -> str:
        """提交视频生成任务，返回 task_id

        Args:
            prompt: 视频提示词
            first_frame_url: 首帧图片URL
            last_frame_url: 尾帧图片URL
            aspect_ratio: 宽高比（16:9, 4:3, 1:1, 3:4, 9:16, 21:9）
            frames: 视频帧数（121=5秒，241=10秒）
        """
        url = f"{self.base_url}/tasks/generations"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "prompt": prompt,
            "aspect_ratio": self._get_aspect_ratio(aspect_ratio),
            "frames": frames,
            "seed": -1,
        }

        # 即梦首尾帧控制：使用 image_urls 数组 [首帧, 尾帧]
        if first_frame_url and last_frame_url:
            payload["image_urls"] = [first_frame_url, last_frame_url]
        elif first_frame_url:
            # 只有首帧
            payload["image_urls"] = [first_frame_url]

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            # 根据API实际行为，初始响应中 task_id 为空，需要使用 request_id
            data = result.get("data", {})
            task_id = data.get("request_id") or data.get("task_id") or result.get("request_id")
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

            # 根据API文档，状态在 data.status 中
            data = result.get("data", {})
            status = data.get("status", "").upper()

            if status == "COMPLETED":
                return result
            elif status in ["FAILED", "CANCELLED"]:
                fail_reason = data.get("fail_reason") or result.get("message") or "任务失败"
                raise ValueError(f"视频生成失败: {fail_reason}")
            elif status in ["SUBMITTING", "SUBMITTED", "IN_PROGRESS"]:
                progress = data.get("progress", "0%")
                print(f"视频生成中... 状态: {status}, 进度: {progress}")
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
        optimized_script: str = "",
        total_segments: int = 1,
        extra_prompt: str = "",
    ) -> GeneratedVideo:
        """基于参考图片生成视频

        Args:
            segment: 分片脚本
            first_image_url: 首帧图片URL
            last_image_url: 尾帧图片URL
            video_params: 视频参数
            optimized_script: 优化后的总脚本（作为上下文）
            total_segments: 总分片数
            extra_prompt: 额外的提示词，用于增加控制力（如：流畅过渡、电影感等）
        """
        # 构建视频提示词
        video_prompt = self._build_video_prompt(
            segment, video_params, optimized_script, total_segments, extra_prompt
        )
        frames = self._get_frames(segment.duration)
        duration = self._get_duration_from_frames(frames)

        try:
            # 使用即梦首尾帧控制功能
            task_id = await self._submit_video_task(
                prompt=video_prompt,
                first_frame_url=first_image_url if first_image_url else None,
                last_frame_url=last_image_url if last_image_url else None,
                aspect_ratio=video_params.aspect_ratio,
                frames=frames,
            )
            print(f"【视频任务已提交-首尾帧】 (分片 {segment.index}): task_id={task_id}, frames={frames}")

            # 等待任务完成
            result = await self._wait_for_task(task_id)

            # 根据API文档，视频URL在 data.data.video_urls 中
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
                prompt=video_prompt
            )

        except Exception as e:
            print(f"--生成视频失败 (分片 {segment.index}): {e}")
            return GeneratedVideo(
                segment_index=segment.index,
                video_id=f"error_{segment.index}",
                video_path="",
                duration=0,
                prompt=f"生成失败: {str(e)}"
            )

    def _build_video_prompt(
        self,
        segment: ScriptSegment,
        video_params: VideoParams,
        optimized_script: str = "",
        total_segments: int = 1,
        extra_prompt: str = "",
    ) -> str:
        """构建完整的视频提示词，包含总脚本上下文

        Args:
            segment: 分片脚本
            video_params: 视频参数
            optimized_script: 优化后的总脚本
            total_segments: 总分片数
            extra_prompt: 额外的提示词
        """
        parts = []

        # 1. 添加总脚本背景（如果有）
        if optimized_script:
            # 截取关键信息作为背景，避免过长
            script_summary = optimized_script[:500] + "..." if len(optimized_script) > 500 else optimized_script
            parts.append(f"[Video Background]: {script_summary}")

        # 2. 添加分片位置信息
        parts.append(f"[Segment {segment.index + 1}/{total_segments}]")

        # 3. 添加分片核心内容
        parts.append(segment.content)

        # 4. 添加动作描述
        if segment.action:
            parts.append(f"Action: {segment.action}")

        # 5. 添加镜头运动
        if segment.camera_movement:
            parts.append(f"Camera: {segment.camera_movement}")

        # 6. 添加镜头效果
        if segment.focus:
            parts.append(f"Lens: {segment.focus}")

        # 7. 添加氛围
        if segment.atmosphere:
            parts.append(f"Atmosphere: {segment.atmosphere}")

        # 8. 添加视频风格
        parts.append(f"Style: {video_params.style}")

        # 9. 添加额外的自定义提示词
        if extra_prompt:
            parts.append(f"[User Requirements]: {extra_prompt}")

        return ", ".join(parts)

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
