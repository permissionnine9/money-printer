"""视频创作工作流 V2 - 4 步流程

工作流程：
1. select_episode: 从剧本会话选集（绑定分集设计与视频参数）
2. storyboard_outline: 分镜大纲（导图 + 分镜列表，见 storyboard.py）
3. segment_management: 分镜管理（分镜形式/overlap 配置 + 提示词生成，见 storyboard.py）
4. generate_videos: 生成视频（远程ComfyUI整段时间轴，支持mock）
"""
import uuid
import logging

from backend.core.models import (
    VideoParams,
    ScriptSegment,
    SegmentFrame,
)
from backend.core.config import (
    VIDEO_SERVICE_TYPE,
)
from backend.core.services import get_legacy_video_service, VideoServiceComfyUI
from backend.core.services.script_context_service import ScriptContextService
from backend.core.persistence import SessionManager

logger = logging.getLogger(__name__)


class VideoCreationWorkflowV2:
    """视频创作工作流 V2 - 4 步流程（剧本创作工作流的下游）

    1. select_episode: 从剧本会话选集（绑定分集设计与视频参数）
    2. storyboard_outline: 分镜大纲（导图 + 分镜列表，见 storyboard.py）
    3. segment_management: 分镜管理（分镜形式/overlap 配置 + 提示词生成，见 storyboard.py）
    4. generate_videos: 生成视频（远程ComfyUI整段时间轴，支持mock）
    """

    def __init__(
        self,
        db_path: str = "data/sessions.db",
        session_manager: SessionManager | None = None
    ):
        """初始化工作流

        Args:
            db_path: 数据库路径（当 session_manager 为 None 时使用）
            session_manager: 可选的 SessionManager 实例（用于依赖注入）
        """
        # 剧本上下文装配（分集设计 → 分镜/参考图/帧 prompt 上下文）
        self.script_context = ScriptContextService()
        # ComfyUI 整段视频服务（步骤5主链路）
        self.comfyui_service = VideoServiceComfyUI()
        # 逐分片视频服务（兼容单分片重生成等 legacy 接口）
        self.video_service = get_legacy_video_service()
        # 支持依赖注入，允许共享 SessionManager 实例
        self.session_manager = session_manager or SessionManager(db_path)
        logger.info("VideoCreationWorkflowV2 初始化完成")

    def create_session(self) -> str:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        self.session_manager.create_session(session_id)
        logger.info(f"创建会话: {session_id[:8]}...")
        return session_id

    def get_session_status(self, session_id: str) -> dict:
        """获取会话状态和进度"""
        return self.session_manager.get_session_summary(session_id)

    # ==================== 步骤 1: 从剧本选集 ====================
    def step_select_episode(
        self,
        session_id: str,
        script_session_id: str,
        episode_id: str,
        video_params: dict,
    ) -> dict:
        """步骤1：从剧本会话选集（绑定分集设计与视频参数）

        Args:
            session_id: 视频会话ID
            script_session_id: 剧本会话ID
            episode_id: 选中的分集ID（如 ep_01）
            video_params: 视频参数字典

        Returns:
            执行结果
        """
        logger.info(f"[步骤1] 从剧本选集 - 会话: {session_id[:8]}... 剧本: {script_session_id[:8]}... 分集: {episode_id}")

        # 校验剧本会话与分集（会话创建时已校验过，这里兜底防串改）
        from backend.deps import get_script_session_manager
        script_sm = get_script_session_manager()
        script_info = script_sm.get_session(script_session_id)
        if not script_info or script_info.get("workflow_type") != "script":
            return {"success": False, "error": f"剧本会话不存在: {script_session_id}"}
        if not script_sm.is_step_completed(script_session_id, "episode_design"):
            return {"success": False, "error": "该剧本会话的分集设计尚未完成"}
        from backend.core.persistence.script_manager import ScriptManager
        episode = ScriptManager().get_episode(script_session_id, episode_id)
        if not episode:
            return {"success": False, "error": f"分集不存在: {episode_id}"}

        try:
            VideoParams(**video_params)
        except Exception as e:
            return {"success": False, "error": f"视频参数非法: {e}"}

        result_data = {
            "script_session_id": script_session_id,
            "episode_id": episode_id,
            "episode_title": episode.get("title", ""),
            "video_params": video_params,
        }
        self.session_manager.save_step_result(session_id, "select_episode", result_data)
        logger.info(f"[步骤1] 完成 - 已选择 {episode_id}《{episode.get('title', '')}》")
        return {"success": True, "message": f"已选择分集 {episode_id}《{episode.get('title', '')}》", "data": result_data}

    def get_selected_episode(self, session_id: str) -> dict:
        """读取本会话绑定的剧本选集信息（script_session_id / episode_id / video_params）"""
        step = self.session_manager.get_step_result(session_id, "select_episode")
        if not step:
            raise ValueError("会话未选择剧本分集（旧会话不兼容，请从「创作剧本」重新开始）")
        return step["result_data"]

    def _get_video_segments(self, session_id: str) -> list[dict]:
        """读取视频生成用的分片列表（dict）

        优先旧 generate_segment_scripts（legacy 会话兜底）；
        否则从 storyboard_outline.segments 映射（content=已生成提示词或分镜大纲，
        duration=max_segment_duration）。新会话无首尾帧数据时视频链路自然进入缺数据态。
        """
        legacy = self.session_manager.get_step_result(session_id, "generate_segment_scripts")
        if legacy and legacy.get("result_data", {}).get("segment_scripts"):
            return legacy["result_data"]["segment_scripts"]

        outline = self.session_manager.get_step_result(session_id, "storyboard_outline")
        if outline and outline.get("result_data", {}).get("segments"):
            selected = self.get_selected_episode(session_id)
            duration = float((selected.get("video_params") or {}).get("max_segment_duration", 15))
            return [
                {
                    "index": seg.get("index", i),
                    "content": seg.get("prompt") or seg.get("outline", ""),
                    "duration": duration,
                }
                for i, seg in enumerate(outline["result_data"]["segments"])
            ]
        return []

    # ==================== 步骤 7: 生成视频 ====================
    async def step_generate_videos(self, session_id: str, extra_prompt: str = "") -> dict:
        """步骤7：生成视频

        两种链路（由 VIDEO_SERVICE_TYPE 决定）：
        1. comfyui（默认）：上传首帧/音频素材到远程 ComfyUI，构造 timeline_data
           整段提交生成最终长视频（远程不可用时 mock 本地合成演示视频）
        2. legacy（doubao/jimeng/wan22）：逐分片首尾帧生成（含视频快照依赖链路）

        Args:
            session_id: 会话ID
            extra_prompt: 自定义提示词，用于增加控制力（如：流畅过渡、电影感等）

        Returns:
            执行结果
        """
        logger.info(f"[步骤7] 生成视频 - 会话: {session_id[:8]}...")
        if extra_prompt:
            logger.info(f"[步骤7] 使用自定义提示词: {extra_prompt[:100]}...")

        # 检查前置步骤
        can_execute, reason = self.session_manager.can_execute_step(session_id, "generate_videos")
        if not can_execute:
            return {"success": False, "error": reason}

        # ComfyUI 整段时间轴生成链路
        if VIDEO_SERVICE_TYPE == "comfyui":
            return await self._step_generate_videos_comfyui(session_id, extra_prompt)

        return await self._step_generate_videos_legacy(session_id, extra_prompt)

    async def _step_generate_videos_comfyui(self, session_id: str, extra_prompt: str = "") -> dict:
        """步骤7（ComfyUI 链路）：上传材料 → 构造 timeline_data → 整段生成最终视频"""
        logger.info(f"[步骤7][ComfyUI] 整段视频生成 - 会话: {session_id[:8]}...")

        # 获取首尾帧、分片脚本和参数
        frames_result = self.session_manager.get_step_result(session_id, "generate_segment_frames")
        selected_episode = self.get_selected_episode(session_id)

        segment_frames = frames_result['result_data'].get('segment_frames', []) if frames_result else []
        segments = self._get_video_segments(session_id)
        params = selected_episode['video_params']
        overlap_seconds = float(params.get('overlap_seconds', 0) or 0)

        try:
            # 收集各分片首帧（缺失首帧的分片不传参考图，仅靠提示词生成）
            frame_image_paths = {}
            for frame in segment_frames:
                idx = frame.get('segment_index', -1)
                path = frame.get('first_image_path') or ""
                if idx >= 0 and path:
                    frame_image_paths[idx] = path

            # 收集会话音频资产（参考音频）
            audio_assets = self.session_manager.list_assets(session_id, asset_type="audio")

            if extra_prompt:
                # 用户自定义提示词并入每段提示词
                segments = [dict(seg, content=f"{seg.get('content', '')}。{extra_prompt}") for seg in segments]

            logger.info(
                f"[步骤7][ComfyUI] 材料: {len(frame_image_paths)} 张首帧, {len(audio_assets)} 个音频, "
                f"overlap={overlap_seconds}s, mock={self.comfyui_service.mock}"
            )

            # 生成最终视频（mock 模式本地合成演示视频）
            result = await self.comfyui_service.generate_full_video(
                segments=segments,
                frame_image_paths=frame_image_paths,
                audio_assets=audio_assets,
                overlap_seconds=overlap_seconds,
            )

            timeline = result["timeline_data"]
            result_data = {
                "generated_videos": [
                    {
                        "segment_index": i,
                        "video_id": result.get("prompt_id", ""),
                        "video_path": result["video_path"],
                        "duration": round((seg.get("endFrame", 0) - seg.get("startFrame", 0)) / timeline.get("fps", 24), 2),
                        "prompt": seg.get("prompt", ""),
                        "task_status": "completed",
                    }
                    for i, seg in enumerate(timeline["segmentConfig"]["segments"])
                ],
                "video_count": len(segments),
                "success_count": len(segments),
                "failed_count": 0,
                "final_video": {
                    "video_path": result["video_path"],
                    "prompt_id": result.get("prompt_id", ""),
                    "mock": result.get("mock", False),
                    "overlap_seconds": timeline.get("_overlap_seconds", 0),
                    "segment_count": len(segments),
                },
                "timeline_data": timeline,
                "_generating": False,
                "_success": True,
            }

            self.session_manager.save_step_result(session_id, "generate_videos", result_data)
            self.session_manager.update_session_status(session_id, "completed")

            mode_text = "（mock 演示视频）" if result.get("mock") else ""
            logger.info(f"[步骤7][ComfyUI] 完成 - 最终视频已生成{mode_text}: {result['video_path']}")

            return {
                "success": True,
                "message": f"最终视频生成完成{mode_text}",
                "data": result_data
            }

        except Exception as e:
            logger.error(f"[步骤7][ComfyUI] 失败: {str(e)}")
            # 保存失败状态
            failure_data = {
                "generated_videos": [],
                "video_count": 0,
                "success_count": 0,
                "failed_count": 1,
                "_generating": False,
                "_success": False,
                "error": str(e),
            }
            self.session_manager.save_step_result(session_id, "generate_videos", failure_data, success=False)
            return {"success": False, "error": f"视频生成失败: {str(e)}", "data": failure_data}

    async def _step_generate_videos_legacy(self, session_id: str, extra_prompt: str = "") -> dict:
        """步骤7（legacy 链路）：逐分片生成视频（支持视频快照依赖链路）"""

        # 获取首尾帧、分片脚本和参数
        frames_result = self.session_manager.get_step_result(session_id, "generate_segment_frames")
        selected_episode = self.get_selected_episode(session_id)

        # 处理 segment_frames 数据，将 None 值转换为 ""（新会话无首尾帧数据则为空列表）
        raw_frames = frames_result['result_data'].get('segment_frames', []) if frames_result else []
        cleaned_frames = []
        for frame in raw_frames:
            cleaned_frame = {}
            for key, value in frame.items():
                # 将 None 转换为 ""，保持其他值不变
                cleaned_frame[key] = "" if value is None else value
            cleaned_frames.append(cleaned_frame)
        segment_frames = [SegmentFrame(**frame) for frame in cleaned_frames]
        segment_scripts = [ScriptSegment(**seg) for seg in self._get_video_segments(session_id)]
        params = selected_episode['video_params']

        try:
            video_params = VideoParams(**params)
            total_segments = len(segment_scripts)

            # 初始化完整的视频列表（包含所有分片，初始状态为 pending）
            from backend.core.models import GeneratedVideo
            all_videos = []
            for segment in segment_scripts:
                all_videos.append(GeneratedVideo(
                    segment_index=segment.index,
                    video_id="",
                    video_path="",
                    duration=0.0,
                    prompt="",
                    task_status="pending"
                ))

            # 识别使用视频快照模式的分片
            snapshot_segments = set()
            for seg in segment_scripts:
                if seg.first_frame_mode == 'use_video_snapshot':
                    snapshot_segments.add(seg.index)

            if snapshot_segments:
                logger.info(f"[步骤7] 发现 {len(snapshot_segments)} 个使用视频快照模式的分片: {sorted(snapshot_segments)}")

            # 按顺序处理每个分片
            for i, segment in enumerate(segment_scripts):
                # 检查是否被取消
                if self.session_manager.is_step_cancelled(session_id, "generate_videos"):
                    logger.warning(f"[步骤7] 视频生成已被用户取消 - 会话: {session_id[:8]}...")
                    # 将未处理的视频标记为 cancelled 状态
                    for j in range(i, total_segments):
                        all_videos[j].task_status = "cancelled"

                    # 保存完整列表（包含已生成、已取消的所有视频）
                    success_count = sum(1 for v in all_videos if v.task_status == "completed")
                    failed_count = sum(1 for v in all_videos if v.task_status == "failed")
                    cancelled_count = sum(1 for v in all_videos if v.task_status == "cancelled")

                    result_data = {
                        "generated_videos": [v.model_dump() for v in all_videos],
                        "video_count": total_segments,
                        "success_count": success_count,
                        "failed_count": failed_count,
                        "cancelled_count": cancelled_count,
                        "_generating": False,
                        "_success": False,
                        "_cancelled": True
                    }
                    self.session_manager.save_step_result(session_id, "generate_videos", result_data, success=False)
                    logger.info(f"[步骤7] 已停止 - 已生成 {success_count}/{total_segments} 个视频，{cancelled_count} 个已取消")

                    return {
                        "success": False,
                        "error": f"视频生成已取消（已生成 {success_count}/{total_segments} 个视频）",
                        "data": result_data
                    }

                # 找到对应的首尾帧
                frame = next(
                    (f for f in segment_frames if f.segment_index == segment.index),
                    None
                )

                # 检查是否是视频快照模式
                is_snapshot_mode = segment.first_frame_mode == 'use_video_snapshot'

                if is_snapshot_mode:
                    # 视频快照模式：需要从前一个分片的视频中截取最后一帧
                    if i == 0:
                        logger.error(f"[步骤7] 分片 {segment.index} 是第一个分片，无法使用视频快照模式")
                        all_videos[i].task_status = "failed"
                        all_videos[i].video_path = "生成失败: 第一个分片无法使用视频快照"
                        continue

                    # 获取前一个分片的视频
                    prev_video = all_videos[i - 1]
                    if prev_video.task_status != "completed" or not prev_video.video_path:
                        logger.error(f"[步骤7] 分片 {segment.index} 的前一个分片视频未生成成功")
                        all_videos[i].task_status = "failed"
                        all_videos[i].video_path = "生成失败: 前一个分片视频未生成成功"
                        continue

                    # 截取前一个视频的最后一帧
                    from backend.core.utils.video_utils import extract_last_frame
                    snapshot_path = extract_last_frame(prev_video.video_path)

                    if not snapshot_path:
                        logger.error(f"[步骤7] 无法从分片 {i-1} 的视频截取快照")
                        all_videos[i].task_status = "failed"
                        all_videos[i].video_path = "生成失败: 无法截取视频快照"
                        continue

                    logger.info(f"[步骤7] 已从分片 {i-1} 的视频截取快照: {snapshot_path}")

                    # 更新当前分片的首帧为截取的快照
                    frame.first_image_path = snapshot_path
                    frame.first_status = "completed"

                    # 更新数据库中的首尾帧数据
                    self._update_frame_with_snapshot(session_id, segment.index, snapshot_path)

                # 检查首帧是否存在（对于非快照模式，或者快照截取失败的情况）
                if not frame or not frame.first_image_path:
                    # 标记为失败并继续处理下一个
                    all_videos[i].task_status = "failed"
                    all_videos[i].video_path = f"生成失败: 分片 {segment.index} 缺少首帧"
                    logger.error(f"[步骤7] 分片 {segment.index} 缺少首帧，跳过")
                    continue

                # 获取前后分片（用于上下文连贯）
                prev_segment = segment_scripts[i - 1] if i > 0 else None
                next_segment = segment_scripts[i + 1] if i < len(segment_scripts) - 1 else None

                # 根据视频生成模式选择不同的生成方法
                video_generation_mode = getattr(segment, 'video_generation_mode', 'first_last_frame')

                if video_generation_mode == 'first_frame_reference':
                    # 首帧+参考图模式：使用豆包seedance-pro，首帧+素材参考图+提示词
                    logger.info(f"[步骤7] 分片 {segment.index} 使用首帧+参考图模式生成视频")

                    # 获取素材图作为参考
                    material_result = self.session_manager.get_step_result(session_id, "generate_episode_reference_images")
                    reference_images = []
                    if material_result and 'result_data' in material_result:
                        raw_material_images = material_result['result_data'].get('material_images', [])
                        reference_images = [
                            img['image_path'] for img in raw_material_images
                            if img.get('image_path') and img.get('task_status') == 'completed'
                        ]

                    # 使用首帧+参考图模式生成视频
                    video = await self.video_service.generate_video_from_first_frame(
                        segment,
                        frame.first_image_path,
                        video_params,
                        reference_images=reference_images if reference_images else None,
                        total_segments=total_segments,
                        extra_prompt=extra_prompt,
                        prev_segment=prev_segment,
                        next_segment=next_segment,
                    )
                else:
                    # 默认：首尾帧模式
                    logger.info(f"[步骤7] 分片 {segment.index} 使用首尾帧模式生成视频")
                    video = await self.video_service.generate_video_from_frames(
                        segment,
                        frame.first_image_path,
                        frame.last_image_path,
                        video_params,
                        total_segments=total_segments,
                        extra_prompt=extra_prompt,
                        prev_segment=prev_segment,
                        next_segment=next_segment,
                    )

                # 确保设置 task_status
                if not hasattr(video, 'task_status') or not video.task_status:
                    # 根据 video_path 判断状态
                    if video.video_path and not video.video_path.startswith("生成失败"):
                        video.task_status = "completed"
                    elif video.video_path and video.video_path.startswith("生成失败"):
                        video.task_status = "failed"
                    else:
                        video.task_status = "pending"

                # 更新对应索引的视频状态
                all_videos[i] = video

                # 每生成一个视频后，保存当前进度（包含所有视频的完整列表）
                success_count = sum(1 for v in all_videos if v.task_status == "completed")
                failed_count = sum(1 for v in all_videos if v.task_status == "failed")
                pending_count = sum(1 for v in all_videos if v.task_status == "pending")

                intermediate_data = {
                    "generated_videos": [v.model_dump() for v in all_videos],
                    "video_count": total_segments,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "pending_count": pending_count,
                    "_generating": True,  # 仍在生成中
                    "_success": False
                }
                # 不推进 current_step，仅更新数据
                self.session_manager.update_step_result(session_id, "generate_videos", intermediate_data)
                logger.info(f"[步骤7] 进度更新: {success_count + failed_count}/{total_segments} 个视频已处理")

            # 统计成功和失败
            success_count = sum(1 for v in all_videos if v.task_status == "completed")
            failed_count = sum(1 for v in all_videos if v.task_status == "failed")

            # 保存结果（使用完整的视频列表）
            result_data = {
                "generated_videos": [v.model_dump() for v in all_videos],
                "video_count": total_segments,
                "success_count": success_count,
                "failed_count": failed_count,
                "_generating": False,  # 标记生成完成
                "_success": failed_count == 0  # 根据是否有错误判断成功状态
            }

            if failed_count > 0:
                self.session_manager.save_step_result(session_id, "generate_videos", result_data, success=False)
                logger.error(f"[步骤7] 部分失败 - {failed_count} 个视频生成失败")
                return {
                    "success": False,
                    "error": f"视频生成部分失败：{failed_count} 个视频生成失败",
                    "data": result_data
                }

            self.session_manager.save_step_result(session_id, "generate_videos", result_data)

            # 更新会话状态为已完成
            self.session_manager.update_session_status(session_id, "completed")
            logger.info(f"[步骤7] 完成 - 生成 {success_count} 个视频片段")

            return {
                "success": True,
                "message": f"已生成 {success_count} 个视频片段",
                "data": result_data
            }

        except Exception as e:
            logger.error(f"[步骤7] 失败: {str(e)}")
            return {"success": False, "error": f"视频生成失败: {str(e)}"}

    def _update_frame_with_snapshot(self, session_id: str, segment_index: int, snapshot_path: str) -> bool:
        """更新分片的首帧为视频快照

        Args:
            session_id: 会话ID
            segment_index: 分片索引
            snapshot_path: 快照图片路径

        Returns:
            是否成功
        """
        try:
            frames_result = self.session_manager.get_step_result(session_id, "generate_segment_frames")
            if not frames_result:
                return False

            segment_frames = frames_result['result_data'].get('segment_frames', [])
            for frame in segment_frames:
                if frame.get('segment_index') == segment_index:
                    frame['first_image_path'] = snapshot_path
                    frame['first_status'] = 'completed'
                    frame['first_prompt'] = '从上一视频快照获取'
                    import uuid
                    frame['first_image_id'] = str(uuid.uuid4())
                    break

            frames_result['result_data']['segment_frames'] = segment_frames
            self.session_manager.update_step_result(session_id, "generate_segment_frames", frames_result['result_data'])
            logger.info(f"[视频快照] 已更新分片 {segment_index} 的首帧为视频快照")
            return True
        except Exception as e:
            logger.error(f"[视频快照] 更新分片 {segment_index} 首帧失败: {e}")
            return False
