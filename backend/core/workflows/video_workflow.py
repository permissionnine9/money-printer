"""视频创作工作流 V2 - 4 步流程

工作流程：
1. select_episode: 从剧本会话选集（绑定分集设计与视频参数）
2. storyboard_outline: 分镜大纲（导图 + 分镜列表，见 agents/storyboard.py）
3. segment_management: 分镜管理（分镜形式/overlap 配置 + 提示词生成，见 agents/storyboard.py）
4. generate_videos: 生成视频（远程ComfyUI整段时间轴，支持mock）
"""
import asyncio
import logging

from backend.core.errors import WorkflowError
from backend.core.models import VideoParams
from backend.core.persistence import SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore
from backend.core.services import VideoServiceComfyUI
from backend.core.services.workspace_sections import get_selected_episode

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
        session_manager: SessionManager | None = None,
        store: WorkspaceStore | None = None,
    ):
        """初始化工作流

        Args:
            db_path: 数据库路径（当 session_manager 为 None 时使用）
            session_manager: 可选的 SessionManager 实例（用于依赖注入）
            store: 文件化工作区存储（deps 构造注入）
        """
        # ComfyUI 整段视频服务（生成视频主链路）
        self.comfyui_service = VideoServiceComfyUI()
        # 支持依赖注入，允许共享 SessionManager 实例
        self.session_manager = session_manager or SessionManager(db_path)
        if store is None:
            raise ValueError("VideoCreationWorkflowV2 需要构造注入 WorkspaceStore（store 参数）")
        self.store = store
        logger.info("VideoCreationWorkflowV2 初始化完成")

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
            raise WorkflowError(f"剧本会话不存在: {script_session_id}")
        if not script_sm.is_step_completed(script_session_id, "episode_design"):
            raise WorkflowError("该剧本会话的分集设计尚未完成")
        try:
            episode = self.store.get_episode(script_session_id, episode_id)
        except ValueError as e:
            raise WorkflowError(str(e))  # 非法 ID 格式（schema 已拦，纵深兜底）
        if not episode:
            raise WorkflowError(f"分集不存在: {episode_id}", status_code=404)

        try:
            VideoParams(**video_params)
        except Exception as e:
            raise WorkflowError(f"视频参数非法: {e}")

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
        return get_selected_episode(self.session_manager, session_id)

    def get_video_segments(self, session_id: str) -> list[dict]:
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
        except WorkflowError:
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

    def _configured_segment_indexes(self, session_id: str) -> set[int]:
        """读取已点「完成当前分镜配置」的分镜 index 集合（新会话门禁；legacy/无分镜返回空集）"""
        try:
            selected = self.get_selected_episode(session_id)
        except WorkflowError:
            return set()
        sb = self.store.read_storyboard(
            selected.get("script_session_id", ""), selected.get("episode_id", ""), session_id,
        )
        if not sb or not sb.get("segments"):
            return set()
        return {s.get("index", i) for i, s in enumerate(sb["segments"]) if s.get("configured")}

    def _resolve_generation_segments(
        self, session_id: str, segment_indexes: list[int] | None = None, *, gate: bool = True,
    ) -> list[dict]:
        """解析本次参与生成的分镜集合（勾选子集；缺省=全部已配置分镜）

        新会话要求 ≥1 个分镜 configured；legacy 会话（旧 segment_scripts 兜底）无
        configured 概念，退化为全部分镜。返回按原次序排列的分段子集。
        gate=False 时只按 index 过滤不重跑门禁（后台任务按 mark_videos_generating
        落盘的 segment_indexes 消费，生成期间取消 configured 不应中断任务）。
        """
        segments = self.get_video_segments(session_id)
        if not segments:
            raise WorkflowError("无可用分镜数据，请先生成分镜大纲")

        if segment_indexes is not None and not segment_indexes:
            raise WorkflowError("请至少勾选一个分镜")

        if gate:
            configured = self._configured_segment_indexes(session_id)
            allowed = configured if configured else {s.get("index", i) for i, s in enumerate(segments)}
            if not configured:
                # legacy 会话无 per-segment 完成标志，跳过门禁（全部分镜可生成）
                legacy = self.session_manager.get_step_result(session_id, "generate_segment_scripts")
                if not (legacy and legacy.get("result_data", {}).get("segment_scripts")):
                    raise WorkflowError("请先在步骤3完成至少一个分镜的配置")
        else:
            allowed = {s.get("index", i) for i, s in enumerate(segments)}

        if segment_indexes is None:
            chosen = allowed
        else:
            chosen = set(segment_indexes)
            missing = chosen - {s.get("index", i) for i, s in enumerate(segments)}
            if missing:
                raise WorkflowError(f"分镜 {', '.join(str(i) for i in sorted(missing))} 不存在")
            if gate:
                unconfigured = chosen - allowed
                if unconfigured:
                    raise WorkflowError(f"分镜 {', '.join(str(i) for i in sorted(unconfigured))} 尚未完成配置")
        return [s for i, s in enumerate(segments) if s.get("index", i) in chosen]

    # ==================== 步骤 4: 生成视频（状态机操作） ====================

    @staticmethod
    def _initial_video(segment_index: int, old: dict | None = None) -> dict:
        """构建单个视频的 pending 初始状态；old 有旧视频时保留备份字段"""
        video = {
            "segment_index": segment_index,
            "video_id": "",
            "video_path": "",
            "duration": 0.0,
            "prompt": "",
            "task_status": "pending",
        }
        if old and old.get("video_path"):
            video["_old_video_path"] = old.get("video_path")  # 备份旧路径
            video["_old_video_id"] = old.get("video_id", "")
        return video

    @classmethod
    def _build_initial_videos(cls, segments: list[dict], existing_videos: list[dict] | None = None) -> list[dict]:
        """构建视频生成初始状态（所有视频标记为 pending；有旧视频的保留备份）"""
        existing_videos = existing_videos or []
        initial = []
        for segment in segments:
            seg_idx = segment.get("index", 0)
            existing = next((v for v in existing_videos if v.get("segment_index") == seg_idx), None)
            initial.append(cls._initial_video(seg_idx, existing))
        return initial

    def mark_videos_generating(
        self, session_id: str, *, regenerate: bool = False, segment_indexes: list[int] | None = None,
    ) -> dict:
        """生成前写 _generating 初始状态并落盘，返回 initial_data

        regenerate=True 时校验步骤4已完成并保留旧视频备份（reset 步骤后重建初始状态）。
        segment_indexes 为勾选分镜子集（缺省=全部已配置分镜）。
        门禁：分镜大纲已完成 + ≥1 个分镜 configured（不再要求 segment_management 步骤完成）。
        校验失败抛 WorkflowError（main.py 全局 handler 转 HTTP detail）。
        """
        step = "generate_videos"
        if not self.session_manager.is_step_completed(session_id, "storyboard_outline"):
            raise WorkflowError("请先完成步骤2：分镜大纲")
        if regenerate:
            if not self.session_manager.is_step_completed(session_id, step):
                raise WorkflowError("步骤4尚未完成，请使用正常生成接口")
            if not self.session_manager.reset_current_step(session_id, step):
                raise WorkflowError("重置步骤状态失败", status_code=500)

        segments = self._resolve_generation_segments(session_id, segment_indexes)

        if regenerate:
            existing = self.session_manager.get_step_result(session_id, step)
            existing_videos = existing["result_data"].get("generated_videos", []) if existing else []
            initial_videos = self._build_initial_videos(segments, existing_videos)
        else:
            initial_videos = self._build_initial_videos(segments)

        initial_data = {
            "generated_videos": initial_videos,
            "video_count": len(initial_videos),
            "segment_indexes": [s.get("index", i) for i, s in enumerate(segments)],
            "success_count": 0,
            "failed_count": 0,
            "final_video": None,   # ComfyUI 整段生成的最终视频（完成后填充）
            "_generating": True,   # 标记为生成中
            "_success": False      # 标记为未完成
        }
        if regenerate:
            initial_data["_backed_up_count"] = sum(1 for v in initial_videos if "_old_video_path" in v)
            initial_data.pop("final_video")  # 重生成态无最终视频（与旧行为一致）
        self.session_manager.save_step_result(session_id, step, initial_data, success=False)
        logger.info(
            f"[步骤4] 已写入{'待重新生成' if regenerate else '生成中'}状态 - 会话: {session_id[:8]}..."
        )
        return initial_data

    def restore_videos_backup(self, session_id: str) -> dict:
        """恢复备份的视频（将 _old_video_path 恢复为 video_path），返回恢复后的 result_data"""
        existing = self.session_manager.get_step_result(session_id, "generate_videos")
        if not existing:
            raise WorkflowError("未找到视频数据", status_code=404)

        result_data = existing["result_data"]
        generated_videos = result_data.get("generated_videos", [])

        restored_count = 0
        for video in generated_videos:
            old_path = video.get("_old_video_path")
            if old_path:
                video["video_path"] = old_path
                video["video_id"] = video.get("_old_video_id", "")
                video["task_status"] = "completed"
                video["duration"] = 5.0  # 恢复默认时长
                restored_count += 1

        if restored_count == 0:
            raise WorkflowError("没有可恢复的备份数据")

        result_data["success_count"] = restored_count
        result_data["failed_count"] = len(generated_videos) - restored_count
        result_data["_generating"] = False
        result_data["_success"] = (restored_count == len(generated_videos))

        self.session_manager.save_step_result(session_id, "generate_videos", result_data, success=True)
        logger.info(f"[步骤4] 已恢复 {restored_count} 个视频的备份 - 会话: {session_id[:8]}...")
        return result_data

    def run_generate_videos_sync(self, session_id: str) -> None:
        """同步入口：供 sync BackgroundTasks 线程池调用（线程内开新事件循环跑异步生成）"""
        asyncio.run(self.step_generate_videos(session_id))

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

        # 门禁与勾选集合以 mark_videos_generating 落盘的 result_data 为准（后台任务不重算）
        if not self.session_manager.is_step_completed(session_id, "storyboard_outline"):
            return {"success": False, "error": "请先完成步骤2：分镜大纲"}
        step_result = self.session_manager.get_step_result(session_id, "generate_videos")
        segment_indexes = step_result["result_data"].get("segment_indexes") if step_result else None

        return await self._step_generate_videos_comfyui(session_id, extra_prompt, segment_indexes)

    async def _step_generate_videos_comfyui(
        self, session_id: str, extra_prompt: str = "", segment_indexes: list[int] | None = None,
    ) -> dict:
        """步骤7（ComfyUI 链路）：上传材料 → 构造 timeline_data → 整段生成最终视频（勾选分镜子集拼接）"""
        logger.info(f"[步骤7][ComfyUI] 整段视频生成 - 会话: {session_id[:8]}...")

        # 获取首尾帧、分片脚本和参数
        frames_result = self.session_manager.get_step_result(session_id, "generate_segment_frames")
        selected_episode = self.get_selected_episode(session_id)

        segment_frames = frames_result['result_data'].get('segment_frames', []) if frames_result else []
        params = selected_episode['video_params']
        overlap_seconds = float(params.get('overlap_seconds', 0) or 0)

        try:
            # 只按 mark_videos_generating 落盘的 segment_indexes 过滤（不重跑门禁：
            # 生成期间取消某分镜 configured 不应中断任务）；异常走 except 落失败快照
            segments = self._resolve_generation_segments(session_id, segment_indexes, gate=False)
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
                        # 勾选子集时 timeline 段序对应过滤后 segments，回填原始分镜 index
                        "segment_index": segments[j].get("index", j) if j < len(segments) else j,
                        "video_id": result.get("prompt_id", ""),
                        "video_path": result["video_path"],
                        "duration": round((seg.get("endFrame", 0) - seg.get("startFrame", 0)) / timeline.get("fps", 24), 2),
                        "prompt": seg.get("prompt", ""),
                        "task_status": "completed",
                    }
                    for j, seg in enumerate(timeline["segmentConfig"]["segments"])
                ],
                "video_count": len(segments),
                "segment_indexes": [s.get("index", i) for i, s in enumerate(segments)],
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
