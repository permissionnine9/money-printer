"""远程 ComfyUI 视频生成服务

按远程 ComfyUI（MiniMaxH3TimelinePlanner 节点）的调用约定：
1. 材料文件（图片/音频）先通过 POST /upload/image 上传，取回 {name, subfolder}
2. 构造 timeline_data JSON（版本5，fps=24，segmentConfig 多段 + 逐段 overlap，
   重叠秒数取自各分镜的 overlap 字段——第 3 步分镜管理配置）
3. 填入工作流模板中 timeline_data 输入，POST /prompt 提交
4. GET /history/{prompt_id} 轮询结果，回传视频下载到本地

对齐规则（后端会校验）：
- 每段长度必须是 5 + 17×n 帧（n≥0），最长 3592 帧
- 第一段从帧 0 开始；段间无空隙、必须前进
- overlap 为 0，或满足 overlap % 17 == 5（即 5、22、39…帧），且小于相邻两段长度
- 每段参考图 ≤9、参考音频 ≤3
- segmentConfig.mode 必须为 "timeline"，count 与 segments 数量一致

远程服务不可用时启用 mock（COMFYUI_MOCK=true）：跳过 HTTP 调用，
用 OpenCV 本地合成一段演示视频（按分段着色+编号，段间 overlap 渐变过渡）。
"""
import asyncio
import hashlib
import json
import logging
import time
import uuid
from pathlib import Path

import httpx

from backend.core.config import (
    COMFYUI_BASE_URL,
    COMFYUI_MOCK,
    COMFYUI_WORKFLOW_PATH,
    COMFYUI_WORKFLOW_UI_PATH,
    COMFYUI_TIMELINE_FPS,
)
from backend.core.utils.image_utils import compress_image
from backend.core.utils.path_utils import VIDEO_SAVE_DIR, resolve_project_path

logger = logging.getLogger(__name__)

# 每段长度规则: 5 + 17n
SEGMENT_FRAME_BASE = 5
SEGMENT_FRAME_STEP = 17
MAX_SEGMENT_FRAMES = 3592
# 每段素材上限
MAX_IMAGES_PER_SEGMENT = 9
MAX_AUDIOS_PER_SEGMENT = 3
# 整条时间轴素材池上限（TimelineDirector 工作台加载 timeline.images 时截断，超出部分静默丢引用）
MAX_TIMELINE_IMAGES = 20
# 上传图片压缩参数：素材原图可达 4K，直接上传会让远程解码/编码时内存与显存翻倍
# （1920 已不低于时间轴最高 1080p 输出分辨率，参考画质无损感知）
UPLOAD_IMAGE_MAX_SIZE = 1920
UPLOAD_IMAGE_QUALITY = 85
# 需要压缩的图片后缀（音频等其余类型原样上传）
_UPLOAD_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _align_segment_frames(raw_frames: int) -> int:
    """将帧数对齐到最近的合法段长（5 + 17n，n≥0）"""
    n = round((raw_frames - SEGMENT_FRAME_BASE) / SEGMENT_FRAME_STEP)
    n = max(0, n)
    frames = SEGMENT_FRAME_BASE + SEGMENT_FRAME_STEP * n
    return min(frames, MAX_SEGMENT_FRAMES)


def _align_overlap_frames(raw_frames: int) -> int:
    """将 overlap 帧数对齐到合法值（0 或 5 + 17n）"""
    if raw_frames <= 0:
        return 0
    n = round((raw_frames - SEGMENT_FRAME_BASE) / SEGMENT_FRAME_STEP)
    n = max(1, n)  # overlap > 0 时至少取 5 帧
    return SEGMENT_FRAME_BASE + SEGMENT_FRAME_STEP * n


class TimelineBuilder:
    """构造 ComfyUI timeline_data"""

    @staticmethod
    def build(
        segments: list[dict],
        frame_image_paths: dict[int, str],
        audio_assets: list[dict] | None = None,
        fps: int = COMFYUI_TIMELINE_FPS,
        uploaded_files: dict[str, dict] | None = None,
        reference_image_paths: dict[int, list[str]] | None = None,
        global_prompt: str = "",
    ) -> dict:
        """构造 timeline_data

        段间重叠逐段取自 seg["overlap"]（第 3 步分镜管理配置的「与上一分镜重叠秒数」，
        首段无上一段恒为 0），经帧对齐后作为该段与前段的物理重叠。

        Args:
            segments: 分片脚本列表（dict，含 index/content/duration/overlap 等）
            frame_image_paths: {segment_index: 首帧图片路径}
            audio_assets: 会话音频资产列表 [{asset_id, name, file_path}]
            fps: 时间轴帧率（默认 24）
            uploaded_files: {本地路径: ComfyUI 上传返回的 {name, subfolder}}；
                mock 模式下不传，文件名字段直接使用本地文件名
            reference_image_paths: {segment_index: [参考素材图路径]}（全能参考模式）
            global_prompt: 全局提示词（附加到整条时间轴，timeline_data.globalPrompt）

        Returns:
            timeline_data dict（可直接 json.dumps 填入工作流）
        """
        uploaded_files = uploaded_files or {}
        reference_image_paths = reference_image_paths or {}

        # 定义素材（首帧图）
        images = []
        seg_image_ids: dict[int, str] = {}
        for seg in segments:
            idx = seg.get("index", 0)
            path = frame_image_paths.get(idx, "")
            if not path:
                continue
            image_id = f"img{idx + 1}"
            upload = uploaded_files.get(path)
            file_name = upload["name"] if upload else Path(path).name
            images.append({"id": image_id, "file": file_name})
            seg_image_ids[idx] = image_id

        # 定义素材（分镜参考图，全能参考模式）
        # 同一文件（上传后的服务器名）在池中只定义一次，跨段共享 id：
        # 工作台/执行端按 images 池的条目数计算素材量，不去重会被截断丢引用
        seg_ref_ids: dict[int, list[str]] = {}
        ref_file_ids: dict[str, str] = {}
        for idx, paths in reference_image_paths.items():
            ids = []
            for path in paths:
                upload = uploaded_files.get(path)
                file_name = upload["name"] if upload else Path(path).name
                image_id = ref_file_ids.get(file_name)
                if image_id is None:
                    image_id = f"ref{len(ref_file_ids) + 1}"
                    ref_file_ids[file_name] = image_id
                    images.append({"id": image_id, "file": file_name})
                ids.append(image_id)
            if ids:
                seg_ref_ids[idx] = ids

        # 定义素材（音频）
        audios = []
        audio_ids: list[str] = []
        for asset in (audio_assets or []):
            audio_id = f"aud{len(audios) + 1}"
            path = asset.get("file_path", "")
            upload = uploaded_files.get(path)
            file_name = upload["name"] if upload else Path(path).name
            audios.append({
                "id": audio_id,
                "file": file_name,
                "audioMode": asset.get("audio_mode", "reference"),
            })
            audio_ids.append(audio_id)

        # 构造分段（逐段 overlap：与上一段的重叠帧，首段恒 0）
        timeline_segments = []
        seg_overlap_frames: list[int] = []
        prev_end = 0
        for i, seg in enumerate(segments):
            duration = seg.get("duration", 15) or 15
            seg_frames = _align_segment_frames(round(duration * fps))
            overlap_frames = (
                _align_overlap_frames(round(float(seg.get("overlap", 0) or 0) * fps)) if i > 0 else 0
            )
            start = 0 if i == 0 else prev_end - overlap_frames
            end = start + seg_frames
            prev_end = end
            seg_overlap_frames.append(overlap_frames)

            idx = seg.get("index", i)
            seg_images = ([seg_image_ids[idx]] if idx in seg_image_ids else []) + seg_ref_ids.get(idx, [])
            # 参考音频每段最多 3 个（当前策略：全部音频资产分配给每段）
            seg_audios = audio_ids[:MAX_AUDIOS_PER_SEGMENT]

            timeline_segments.append({
                "startFrame": start,
                "endFrame": end,
                "images": seg_images,
                "audios": seg_audios,
                "prompt": TimelineBuilder.build_segment_prompt(seg),
            })

        return {
            "version": 5,
            "fps": fps,
            "globalPrompt": global_prompt,
            "selection": {"start": 0, "duration": max(1, prev_end // fps)},
            "videoAudioEnabled": True,
            "videoClips": [],
            "images": images,
            "audios": audios,
            "segmentConfig": {
                "count": len(timeline_segments),
                "activeIndex": 0,
                "mode": "timeline",
                "segments": timeline_segments,
            },
            # 附加信息（非 ComfyUI 必需字段，便于前端展示与调试）：
            # 逐段与前段的重叠帧数/秒数（首段恒 0）
            "_overlap_frames": seg_overlap_frames,
            "_overlap_seconds": [round(f / fps, 3) for f in seg_overlap_frames],
        }

    @staticmethod
    def build_segment_prompt(seg: dict) -> str:
        """将分片脚本转为该段的视频生成提示词"""
        parts = [seg.get("content", "")]
        if seg.get("camera_movement"):
            parts.append(f"镜头运动: {seg['camera_movement']}")
        if seg.get("atmosphere"):
            parts.append(f"氛围: {seg['atmosphere']}")
        return "。".join(p for p in parts if p)

    @staticmethod
    def validate(timeline: dict) -> list[str]:
        """校验 timeline_data 对齐规则，返回错误列表（空列表 = 通过）"""
        errors = []
        cfg = timeline.get("segmentConfig", {})
        segs = cfg.get("segments", [])

        if cfg.get("mode") != "timeline":
            errors.append("segmentConfig.mode 必须为 'timeline'")
        if cfg.get("count") != len(segs):
            errors.append(f"count({cfg.get('count')}) 与 segments 数量({len(segs)}) 不一致")
        if len(timeline.get("images", [])) > MAX_TIMELINE_IMAGES:
            errors.append(
                f"参考素材图去重后共 {len(timeline['images'])} 张，"
                f"超过时间轴素材池上限 {MAX_TIMELINE_IMAGES} 张，请精简各分镜的参考图"
            )

        prev_end = 0
        for i, seg in enumerate(segs):
            start, end = seg.get("startFrame", -1), seg.get("endFrame", -1)
            length = end - start
            if (length - SEGMENT_FRAME_BASE) % SEGMENT_FRAME_STEP != 0 or length <= 0:
                errors.append(f"段{i + 1}: 长度 {length} 帧不满足 5+17n 规则")
            if length > MAX_SEGMENT_FRAMES:
                errors.append(f"段{i + 1}: 长度 {length} 帧超过上限 {MAX_SEGMENT_FRAMES}")
            if i == 0 and start != 0:
                errors.append(f"首段必须从帧 0 开始（当前 {start}）")
            if i > 0:
                overlap = prev_end - start
                if overlap < 0:
                    errors.append(f"段{i + 1} 与前段之间存在空隙（overlap={overlap}）")
                elif overlap != 0 and overlap % SEGMENT_FRAME_STEP != SEGMENT_FRAME_BASE % SEGMENT_FRAME_STEP:
                    errors.append(f"段{i + 1}: overlap={overlap} 不满足 0 或 %17==5 规则")
                if overlap >= length:
                    errors.append(f"段{i + 1}: overlap({overlap}) 不小于段长({length})")
            if end <= prev_end and i > 0:
                errors.append(f"段{i + 1} 未前进（endFrame={end} <= 前段 {prev_end}）")
            if len(seg.get("images", [])) > MAX_IMAGES_PER_SEGMENT:
                errors.append(f"段{i + 1}: 参考图超过 {MAX_IMAGES_PER_SEGMENT} 张")
            if len(seg.get("audios", [])) > MAX_AUDIOS_PER_SEGMENT:
                errors.append(f"段{i + 1}: 参考音频超过 {MAX_AUDIOS_PER_SEGMENT} 个")
            prev_end = end

        return errors


class ComfyUIClient:
    """远程 ComfyUI HTTP 客户端"""

    def __init__(self, base_url: str = COMFYUI_BASE_URL, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def upload_file(self, file_path: str) -> dict:
        """上传材料文件（图片/音频均可），返回 {name, subfolder}

        图片先压缩到 UPLOAD_IMAGE_MAX_SIZE 边长的 JPEG 再上传（防远程内存/显存 OOM）；
        压缩失败回退原文件。音频原样上传。
        """
        path = resolve_project_path(file_path)

        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".webp": "image/webp", ".mp3": "audio/mpeg", ".wav": "audio/wav",
                    ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac"}
        mime = mime_map.get(path.suffix.lower(), "application/octet-stream")

        filename, data = path.name, path.read_bytes()
        if path.suffix.lower() in _UPLOAD_IMAGE_EXTS:
            # 压缩失败时 compress_image 返回 (原字节, "image/png")，以 mime 判定成败：
            # 失败或压完反而更大（小 jpg 重压）则原样上传，文件名/mime 保持原值
            compressed, comp_mime = compress_image(data, UPLOAD_IMAGE_MAX_SIZE, UPLOAD_IMAGE_QUALITY)
            if comp_mime == "image/jpeg" and len(compressed) < len(data):
                # 文件名带内容 hash：防同批 a.png/a.jpg 压缩后同名互撞（ComfyUI 对
                # 同名不同内容返回 400），同内容则同名放行（幂等重传）
                filename, data, mime = (
                    f"{path.stem}_{hashlib.md5(compressed).hexdigest()[:8]}.jpg", compressed, comp_mime,
                )
                logger.info(f"[ComfyUI] 图片已压缩: {path.name} -> {filename}（{len(data)} 字节）")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/upload/image",
                files={"image": (filename, data, mime)},
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"[ComfyUI] 上传成功: {filename} -> {result}")
            return {"name": result.get("name", filename), "subfolder": result.get("subfolder", "")}

    def load_workflow_template(self) -> dict:
        """加载 API 格式工作流模板"""
        if not COMFYUI_WORKFLOW_PATH.exists():
            raise FileNotFoundError(
                f"未找到 ComfyUI 工作流模板: {COMFYUI_WORKFLOW_PATH}，"
                f"请将导出的 API 格式工作流保存到该路径"
            )
        return json.loads(COMFYUI_WORKFLOW_PATH.read_text(encoding="utf-8"))

    def load_workflow_ui_template(self) -> dict:
        """加载 UI 格式工作流模板（网页可视化版，供导入后落盘到远程 workflows 库）"""
        if not COMFYUI_WORKFLOW_UI_PATH.exists():
            raise FileNotFoundError(
                f"未找到 ComfyUI UI 格式工作流模板: {COMFYUI_WORKFLOW_UI_PATH}"
            )
        return json.loads(COMFYUI_WORKFLOW_UI_PATH.read_text(encoding="utf-8"))

    async def save_ui_workflow(self, filename: str, workflow: dict) -> str:
        """把 UI 格式工作流保存到远程 workflows 库（TimelineDirector 的 save_workflow 端点）"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/minimax_h3_timeline/save_workflow",
                json={"filename": filename, "workflow": workflow},
            )
            response.raise_for_status()
            name = response.json().get("name", filename)
            logger.info(f"[ComfyUI] UI 工作流已保存到远程: {name}")
            return name

    @staticmethod
    def inject_timeline_data(workflow: dict, timeline_data: dict) -> dict:
        """将 timeline_data 注入工作流中对应节点的输入"""
        injected = 0
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs")
            if isinstance(inputs, dict) and "timeline_data" in inputs:
                inputs["timeline_data"] = json.dumps(timeline_data, ensure_ascii=False)
                injected += 1
        if injected == 0:
            raise ValueError("工作流模板中未找到带 timeline_data 输入的节点")
        logger.info(f"[ComfyUI] timeline_data 已注入 {injected} 个节点")
        return workflow

    @staticmethod
    def inject_timeline_data_ui(workflow: dict, timeline_data: dict) -> dict:
        """将 timeline_data 注入 UI 格式工作流（MiniMaxH3TimelinePlanner 节点的 widgets_values）

        widgets_values 里定位「JSON 解析后为 dict 且含 version 键」的字符串元素替换，
        不依赖参数下标（插件版本升级调整 widget 顺序时依然有效）。
        """
        payload = json.dumps(timeline_data, ensure_ascii=False)
        for node in workflow.get("nodes", []):
            if node.get("type") != "MiniMaxH3TimelinePlanner":
                continue
            widgets = node.get("widgets_values")
            if not isinstance(widgets, list):
                continue
            for i, value in enumerate(widgets):
                if not isinstance(value, str):
                    continue
                try:
                    parsed = json.loads(value)
                except ValueError:
                    continue
                if isinstance(parsed, dict) and "version" in parsed:
                    widgets[i] = payload
                    return workflow
        raise ValueError("UI 工作流模板中未找到 MiniMaxH3TimelinePlanner 的 timeline_data")

    async def submit_prompt(self, workflow: dict) -> str:
        """提交工作流，返回 prompt_id"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/prompt",
                json={"prompt": workflow, "client_id": f"money-printer-{uuid.uuid4().hex[:8]}"},
            )
            response.raise_for_status()
            data = response.json()
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                raise ValueError(f"ComfyUI 未返回 prompt_id: {data}")
            logger.info(f"[ComfyUI] 工作流已提交: {prompt_id}")
            return prompt_id

    async def get_history(self, prompt_id: str) -> dict:
        """查询执行历史"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/history/{prompt_id}")
            response.raise_for_status()
            return response.json().get(prompt_id, {})

    async def wait_for_result(self, prompt_id: str, max_wait: float = 2400.0, poll_interval: float = 5.0) -> dict:
        """轮询直到执行完成，返回 history 条目

        轮询期间的瞬时连接错误（SSH 隧道抖动、远程重启）不视为任务失败，
        连续 ~5 分钟不可达才放弃（覆盖隧道 90s 重连与远程重启窗口）。
        """
        deadline = time.time() + max_wait
        consecutive_errors = 0
        while time.time() < deadline:
            try:
                history = await self.get_history(prompt_id)
                consecutive_errors = 0
                if history:
                    status = history.get("status", {})
                    if status.get("completed") or status.get("status_str") == "error":
                        return history
            except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.TimeoutException) as e:
                consecutive_errors += 1
                logger.warning(f"[ComfyUI] 查询任务状态失败（连续 {consecutive_errors} 次）: {e}")
                if consecutive_errors >= 60:  # ~5 分钟持续不可达
                    raise
            await asyncio.sleep(poll_interval)
        raise TimeoutError(f"等待 ComfyUI 任务 {prompt_id} 超时（{max_wait}s）")

    async def download_output(self, history: dict, save_dir: Path = VIDEO_SAVE_DIR) -> str:
        """从执行结果中找到视频文件并下载到本地"""
        outputs = history.get("outputs", {})
        video_file = None
        for node_output in outputs.values():
            for key in ("videos", "gifs", "images"):
                for item in node_output.get(key, []):
                    if item.get("type") == "output" and not item.get("filename", "").endswith((".png", ".jpg", ".jpeg", ".webp")):
                        video_file = item
                        break
                if video_file:
                    break
            if video_file:
                break

        if not video_file:
            raise ValueError(f"ComfyUI 执行结果中未找到输出视频: {json.dumps(outputs, ensure_ascii=False)[:500]}")

        save_dir.mkdir(parents=True, exist_ok=True)
        local_path = save_dir / f"comfyui_{uuid.uuid4().hex[:8]}_{video_file['filename']}"
        params = {"filename": video_file["filename"], "subfolder": video_file.get("subfolder", ""), "type": "output"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("GET", f"{self.base_url}/view", params=params) as response:
                response.raise_for_status()
                with open(local_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)

        logger.info(f"[ComfyUI] 输出视频已下载: {local_path}")
        return str(local_path)


def _generate_mock_video(timeline: dict, segments: list[dict]) -> str:
    """用 OpenCV 生成一段本地演示视频（mock 模式）

    按分段着色并叠加段号/提示词文字，段间 overlap 区间做线性渐变过渡
    （逐段重叠帧取自 timeline._overlap_frames）。
    """
    import cv2
    import numpy as np

    fps = timeline.get("fps", 24)
    width, height = 1280, 720
    # 逐段重叠帧（列表）；兼容旧暂存 timeline 的单值 int（所有段同一重叠）
    raw_overlaps = timeline.get("_overlap_frames", 0)

    def _seg_overlap(i: int) -> int:
        if isinstance(raw_overlaps, list):
            return raw_overlaps[i] if i < len(raw_overlaps) else 0
        return raw_overlaps if i > 0 else 0
    seg_colors = [
        (80, 120, 200), (90, 170, 120), (190, 140, 80),
        (150, 100, 180), (70, 170, 190), (200, 100, 120),
    ]

    def render_segment_frame(seg_idx: int, prompt: str, t: float, duration: float):
        color = seg_colors[seg_idx % len(seg_colors)]
        # 颜色随时间轻微明暗变化，制造动态感
        k = 0.85 + 0.15 * abs(((t / max(duration, 0.01)) * 2) % 2 - 1)
        frame = np.full((height, width, 3), [int(c * k) for c in color], dtype=np.uint8)
        cv2.putText(frame, f"Segment {seg_idx + 1}/{len(segments)}", (60, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
        cv2.putText(frame, f"t = {t:.1f}s / {duration:.1f}s", (60, 190),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (235, 235, 235), 2)
        # 提示词截断展示
        text = prompt[:60] + ("..." if len(prompt) > 60 else "")
        cv2.putText(frame, text, (60, 640), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 210), 2)
        cv2.putText(frame, "[ComfyUI MOCK VIDEO]", (60, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (120, 255, 120), 2)
        return frame

    seg_defs = []
    for i, seg in enumerate(timeline["segmentConfig"]["segments"]):
        length = seg["endFrame"] - seg["startFrame"]
        prompt = segments[i].get("content", "") if i < len(segments) else ""
        seg_defs.append((length / fps, prompt))

    VIDEO_SAVE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = VIDEO_SAVE_DIR / f"mock_comfyui_{uuid.uuid4().hex[:8]}.mp4"
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))

    try:
        for i, (duration, prompt) in enumerate(seg_defs):
            steps = max(1, int(duration * fps))
            overlap_frames = _seg_overlap(i)
            for s in range(steps):
                t = s / fps
                frame = render_segment_frame(i, prompt, t, duration)
                if i > 0 and overlap_frames > 0 and s < overlap_frames:
                    # overlap 区间与前一段末帧做渐变（简化：与纯色混合）
                    prev_color = seg_colors[(i - 1) % len(seg_colors)]
                    alpha = 1.0 - (s + 1) / overlap_frames
                    prev_frame = np.full((height, width, 3), prev_color, dtype=np.uint8)
                    frame = cv2.addWeighted(frame, alpha, prev_frame, 1 - alpha, 0)
                writer.write(frame)
    finally:
        writer.release()

    logger.info(f"[ComfyUI][mock] 演示视频已生成: {out_path}")
    return str(out_path)


class VideoServiceComfyUI:
    """ComfyUI 视频服务（整段时间轴生成，支持 mock）"""

    def __init__(self, base_url: str = COMFYUI_BASE_URL, mock: bool = COMFYUI_MOCK):
        self.client = ComfyUIClient(base_url)
        self.mock = mock

    async def prepare_import(
        self,
        segments: list[dict],
        frame_image_paths: dict[int, str],
        audio_assets: list[dict] | None = None,
        reference_image_paths: dict[int, list[str]] | None = None,
        global_prompt: str = "",
        ui_workflow_name: str | None = None,
    ) -> dict:
        """阶段一（导入）：构造 timeline → 校验 → 上传材料 → 注入工作流模板

        mock 模式跳过上传与模板加载（workflow 为 None）。
        ui_workflow_name 非空时额外把注入后的 UI 格式工作流落到远程 workflows 库
        （ComfyUI 网页可打开检查/微调）；落盘失败仅告警，不阻断导入。

        Returns:
            {"workflow": 注入后的工作流（mock 为 None）, "timeline_data": dict, "mock": bool,
             "ui_workflow_name": 落盘成功时的远程工作流名（未落盘为 None）}
        """
        timeline = TimelineBuilder.build(
            segments, frame_image_paths, audio_assets,
            reference_image_paths=reference_image_paths, global_prompt=global_prompt,
        )
        errors = TimelineBuilder.validate(timeline)
        if errors:
            raise ValueError(f"timeline_data 校验失败: {'; '.join(errors)}")

        if self.mock:
            logger.info("[ComfyUI][mock] 导入跳过远程上传，timeline 使用本地文件名")
            return {"workflow": None, "timeline_data": timeline, "mock": True,
                    "ui_workflow_name": None}

        # 1. 上传全部材料文件
        upload_paths = set(frame_image_paths.values()) | {
            a.get("file_path") for a in (audio_assets or []) if a.get("file_path")
        } | {p for paths in (reference_image_paths or {}).values() for p in paths}
        uploaded = {}
        for path in upload_paths:
            if path:
                uploaded[path] = await self.client.upload_file(path)

        # 2. 用上传结果重建 timeline（图片/音频文件名替换为 ComfyUI input 目录名）
        timeline = TimelineBuilder.build(
            segments, frame_image_paths, audio_assets,
            uploaded_files=uploaded, reference_image_paths=reference_image_paths,
            global_prompt=global_prompt,
        )
        errors = TimelineBuilder.validate(timeline)
        if errors:
            raise ValueError(f"timeline_data 校验失败: {'; '.join(errors)}")

        # 3. 注入工作流模板（timeline_data → MiniMaxH3TimelinePlanner 素材规划工作台）
        workflow = self.client.load_workflow_template()
        workflow = ComfyUIClient.inject_timeline_data(workflow, timeline)

        # 4. UI 版同步落盘到远程 workflows 库（网页可见是增强能力，失败不阻断导入）
        ui_workflow_saved = None
        if ui_workflow_name:
            try:
                ui_workflow = ComfyUIClient.inject_timeline_data_ui(
                    self.client.load_workflow_ui_template(), timeline
                )
                ui_workflow_saved = await self.client.save_ui_workflow(ui_workflow_name, ui_workflow)
            except Exception as e:
                logger.warning(f"[ComfyUI] UI 工作流落盘失败（不影响导入）: {e}")

        logger.info("[ComfyUI] 导入完成，工作流已就绪（未提交执行）")
        return {"workflow": workflow, "timeline_data": timeline, "mock": False,
                "ui_workflow_name": ui_workflow_saved}

    async def execute_imported(
        self, segments: list[dict], workflow: dict | None, timeline: dict,
    ) -> dict:
        """阶段二（执行）：提交工作流 → 轮询结果 → 下载视频

        mock 模式（workflow 为 None）本地合成演示视频。

        Returns:
            {"success", "video_path", "timeline_data", "mock", "prompt_id"}
        """
        if self.mock or workflow is None:
            logger.info("[ComfyUI][mock] 跳过远程调用，本地生成演示视频")
            video_path = await asyncio.to_thread(_generate_mock_video, timeline, segments)
            return {
                "success": True,
                "video_path": video_path,
                "timeline_data": timeline,
                "mock": True,
                "prompt_id": f"mock-{uuid.uuid4().hex[:8]}",
            }

        # 1. 提交 → 2. 轮询结果 → 3. 下载
        prompt_id = await self.client.submit_prompt(workflow)
        history = await self.client.wait_for_result(prompt_id)
        status = history.get("status", {})
        if status.get("status_str") == "error":
            raise RuntimeError(f"ComfyUI 执行失败: {json.dumps(status, ensure_ascii=False)[:500]}")

        video_path = await self.client.download_output(history)
        return {
            "success": True,
            "video_path": video_path,
            "timeline_data": timeline,
            "mock": False,
            "prompt_id": prompt_id,
        }

    async def generate_full_video(
        self,
        segments: list[dict],
        frame_image_paths: dict[int, str],
        audio_assets: list[dict] | None = None,
        reference_image_paths: dict[int, list[str]] | None = None,
        global_prompt: str = "",
    ) -> dict:
        """生成完整视频：导入（上传+构造+注入）→ 执行（提交+轮询+下载）一步到位

        供 regenerate/legacy 一步式链路使用；两段式交互走 prepare_import + execute_imported。

        Returns:
            {"success", "video_path", "timeline_data", "mock", "prompt_id"}
        """
        prepared = await self.prepare_import(
            segments, frame_image_paths, audio_assets,
            reference_image_paths=reference_image_paths, global_prompt=global_prompt,
        )
        return await self.execute_imported(segments, prepared["workflow"], prepared["timeline_data"])
