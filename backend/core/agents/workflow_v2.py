"""视频创作工作流 V2 - 4 步流程

工作流程：
1. select_episode: 从剧本会话选集（绑定分集设计与视频参数）
2. storyboard_outline: 分镜大纲（导图 + 分镜列表，见 storyboard.py）
3. segment_management: 分镜管理（分镜形式/overlap 配置 + 提示词生成，见 storyboard.py）
4. generate_videos: 生成视频（远程ComfyUI整段时间轴，支持mock）
"""
import uuid
import logging

from backend.core.models import VideoParams
from backend.core.services import VideoServiceComfyUI
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
        # ComfyUI 整段视频服务（生成视频主链路）
        self.comfyui_service = VideoServiceComfyUI()
        # 支持依赖注入，允许共享 SessionManager 实例
        self.session_manager = session_manager or SessionManager(db_path)
        from backend.deps import get_workspace_store
        self.store = get_workspace_store()
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
        episode = self.store.get_episode(script_session_id, episode_id)
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
        否则从工作区分镜文件读取（content=已生成提示词或分镜大纲，
        duration=max_segment_duration）。新会话无首尾帧数据时视频链路自然进入缺数据态。
        """
        legacy = self.session_manager.get_step_result(session_id, "generate_segment_scripts")
        if legacy and legacy.get("result_data", {}).get("segment_scripts"):
            return legacy["result_data"]["segment_scripts"]

        try:
            selected = self.get_selected_episode(session_id)
        except ValueError:
            return []
        sb = self.store.read_storyboard(
            selected.get("script_session_id", ""), selected.get("episode_id", ""), session_id,
        )
        if sb and sb.get("segments"):
            duration = float((selected.get("video_params") or {}).get("max_segment_duration", 15))
            return [
                {
                    "index": seg.get("index", i),
                    "content": seg.get("prompt") or seg.get("outline", ""),
                    "duration": duration,
                    # 全能参考模式的参考素材图（生成视频时作为该段参考图）
                    "reference_images": seg.get("reference_images", []),
                }
                for i, seg in enumerate(sb["segments"])
            ]
        return []

    @staticmethod
    def _videos_snapshot(all_videos: list, total_segments: int, *, generating: bool, success: bool, **extra) -> dict:
        """视频生成进度统一快照（中间进度/取消/最终落盘共用）"""
        snapshot = {
            "generated_videos": [v.model_dump() for v in all_videos],
            "video_count": total_segments,
            "success_count": sum(1 for v in all_videos if v.task_status == "completed"),
            "failed_count": sum(1 for v in all_videos if v.task_status == "failed"),
            "_generating": generating,
            "_success": success,
        }
        snapshot.update(extra)
        return snapshot

    # ==================== 步骤 7: 生成视频 ====================
    async def step_generate_videos(self, session_id: str, extra_prompt: str = "") -> dict:
        """步骤7：生成视频

        上传首帧/音频素材到远程 ComfyUI，构造 timeline_data
        整段提交生成最终长视频（远程不可用时 mock 本地合成演示视频）

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

        return await self._step_generate_videos_comfyui(session_id, extra_prompt)

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

            # 收集各分镜参考素材图（全能参考模式；http(s) 外链无法直接上传，跳过）
            reference_image_paths = {
                seg.get("index", i): [
                    r["image_path"] for r in seg.get("reference_images", []) if r.get("image_path")
                ]
                for i, seg in enumerate(segments)
            }
            reference_image_paths = {
                idx: [p for p in paths if not p.startswith(("http://", "https://"))]
                for idx, paths in reference_image_paths.items() if paths
            }

            # 收集会话音频资产（参考音频）
            audio_assets = self.session_manager.list_assets(session_id, asset_type="audio")

            if extra_prompt:
                # 用户自定义提示词并入每段提示词
                segments = [dict(seg, content=f"{seg.get('content', '')}。{extra_prompt}") for seg in segments]

            logger.info(
                f"[步骤7][ComfyUI] 材料: {len(frame_image_paths)} 张首帧, "
                f"{sum(len(v) for v in reference_image_paths.values())} 张参考图, "
                f"{len(audio_assets)} 个音频, overlap={overlap_seconds}s, mock={self.comfyui_service.mock}"
            )

            # 生成最终视频（mock 模式本地合成演示视频）
            result = await self.comfyui_service.generate_full_video(
                segments=segments,
                frame_image_paths=frame_image_paths,
                audio_assets=audio_assets,
                overlap_seconds=overlap_seconds,
                reference_image_paths=reference_image_paths,
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

