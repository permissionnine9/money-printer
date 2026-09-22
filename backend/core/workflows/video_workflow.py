"""视频创作工作流 V2 - 4 步流程

工作流程：
1. select_episode: 从剧本会话选集（绑定分集设计与视频参数）
2. storyboard_outline: 分镜大纲（导图 + 分镜列表，见 agents/storyboard.py）
3. segment_management: 分镜管理（分镜形式/overlap 配置 + 提示词生成，见 agents/storyboard.py）
4. generate_videos: 生成视频（远程ComfyUI整段时间轴，支持mock）
"""
import asyncio
import logging
import re
from datetime import datetime

import httpx

from backend.core.config import COMFYUI_BASE_URL
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

        # 重新选集（选集/参数变化）：清空后续步骤并删旧分镜目录——先回收分镜素材再删
        # （素材图保留在素材库，素材管理可见、素材池可复用；与前端确认弹窗承诺一致）
        prev = (self.session_manager.get_step_result(session_id, "select_episode") or {}).get("result_data") or {}
        if prev.get("script_session_id") and (
            (prev.get("script_session_id"), prev.get("episode_id"), prev.get("video_params"))
            != (script_session_id, episode_id, video_params)
        ):
            self._cleanup_storyboard_on_reselect(session_id, prev)
            self.session_manager.clear_steps_after(session_id, "select_episode")
            # aux 暂存不在步骤状态机内，clear_steps_after 清不到——必须显式删，
            # 否则重选集后新分镜段数与旧暂存一致时会按旧 timeline 生成旧剧情视频
            self.session_manager.delete_step_result(session_id, "comfyui_import")

        result_data = {
            "script_session_id": script_session_id,
            "episode_id": episode_id,
            "episode_title": episode.get("title", ""),
            "video_params": video_params,
        }
        self.session_manager.save_step_result(session_id, "select_episode", result_data)
        logger.info(f"[步骤1] 完成 - 已选择 {episode_id}《{episode.get('title', '')}》")
        return {"success": True, "message": f"已选择分集 {episode_id}《{episode.get('title', '')}》", "data": result_data}

    def _cleanup_storyboard_on_reselect(self, session_id: str, prev: dict) -> None:
        """重新选集清理：回收分镜素材 → 删除旧分镜目录（分镜脚本作废，素材图保留）"""
        from backend.deps import get_script_manager
        from backend.core.services.material_pool_service import MaterialPoolService

        old_sid = prev.get("script_session_id", "")
        old_ep = prev.get("episode_id", "")
        materials = MaterialPoolService(self.store, get_script_manager())
        recycled = materials.recycle_segment_materials(old_sid, old_ep, session_id)
        if recycled:
            logger.info(f"[步骤1] 重新选集：回收 {recycled} 张分镜素材（{old_ep}）")
        if self.store.delete_storyboard(old_sid, old_ep, session_id):
            logger.info(f"[步骤1] 重新选集：已删除旧分镜目录（{old_ep}/vs-{session_id[:8]}）")

    def get_selected_episode(self, session_id: str) -> dict:
        """读取本会话绑定的剧本选集信息（script_session_id / episode_id / video_params）"""
        return get_selected_episode(self.session_manager, session_id)

    def get_video_segments(self, session_id: str) -> list[dict]:
        """读取视频生成用的分片列表（dict）

        从工作区分镜文件读取（content=已生成提示词或分镜大纲，
        duration=分镜自身时长，缺省回落选集的 max_segment_duration）。
        无首尾帧数据时视频链路自然进入缺数据态。
        """
        try:
            selected = self.get_selected_episode(session_id)
        except WorkflowError:
            return []
        sb = self.store.read_storyboard(
            selected.get("script_session_id", ""), selected.get("episode_id", ""), session_id,
        )
        if sb and sb.get("segments"):
            max_duration = float((selected.get("video_params") or {}).get("max_segment_duration", 15))
            return [
                {
                    "index": seg.get("index", i),
                    "content": seg.get("prompt") or seg.get("outline", ""),
                    # 分镜自身时长（步骤2大纲/步骤3配置）优先，缺省回落选集上限
                    "duration": seg.get("duration") or max_duration,
                    # 与上一分镜的重叠秒数（步骤3配置；时间轴拼接的逐段物理重叠来源）
                    "overlap": seg.get("overlap", 0) or 0,
                    # 全能参考模式的参考素材图（生成视频时作为该段参考图）
                    "reference_images": seg.get("reference_images", []),
                }
                for i, seg in enumerate(sb["segments"])
            ]
        return []

    def _configured_segment_indexes(self, session_id: str) -> set[int]:
        """读取已点「完成当前分镜配置」的分镜 index 集合（生成门禁；无分镜返回空集）"""
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

        要求 ≥1 个分镜 configured；返回按原次序排列的分段子集。
        gate=False 时只按 index 过滤不重跑门禁（后台任务按 mark_videos_generating
        落盘的 segment_indexes 消费，生成期间取消 configured 不应中断任务）。
        """
        segments = self.get_video_segments(session_id)
        if not segments:
            raise WorkflowError("无可用分镜数据，请先生成分镜大纲")

        if segment_indexes is not None and not segment_indexes:
            raise WorkflowError("请至少勾选一个分镜")

        if gate:
            allowed = self._configured_segment_indexes(session_id)
            if not allowed:
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
        # 连续性校验（与前端勾选规则一致）：分镜编号须严格相邻，不可跳选
        chosen_ordered = sorted(chosen)
        if chosen_ordered and chosen_ordered != list(range(chosen_ordered[0], chosen_ordered[0] + len(chosen_ordered))):
            raise WorkflowError("分镜须连续选择（不可跳选），请勾选一段连续的分镜")
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
        self, session_id: str, *, segment_indexes: list[int] | None = None,
    ) -> dict:
        """生成前写 _generating 初始状态并落盘，返回 initial_data

        segment_indexes 为勾选分镜子集（缺省=全部已配置分镜）。
        门禁：分镜大纲已完成 + ≥1 个分镜 configured（不再要求 segment_management 步骤完成）。
        上次已生成过（步骤已完成）时先回退步骤状态，旧分段视频与最终视频保留备份
        （_old_video_path / _old_final_video），支持「生成过后重新勾选再生成」+ 恢复备份。
        校验失败抛 WorkflowError（main.py 全局 handler 转 HTTP detail）。
        """
        step = "generate_videos"
        if not self.session_manager.is_step_completed(session_id, "storyboard_outline"):
            raise WorkflowError("请先完成步骤2：分镜大纲")

        segments = self._resolve_generation_segments(session_id, segment_indexes)

        existing = self.session_manager.get_step_result(session_id, step)
        existing_videos = existing["result_data"].get("generated_videos", []) if existing else []
        old_final_video = existing["result_data"].get("final_video") if existing else None
        if existing and self.session_manager.is_step_completed(session_id, step):
            # 上次生成已完成：回退步骤状态，旧结果走备份（生成中重复调用不备份）
            if not self.session_manager.reset_current_step(session_id, step):
                raise WorkflowError("重置步骤状态失败", status_code=500)
        else:
            existing_videos = []
            old_final_video = None

        initial_videos = self._build_initial_videos(segments, existing_videos)

        initial_data = {
            "generated_videos": initial_videos,
            "video_count": len(initial_videos),
            "segment_indexes": [s.get("index", i) for i, s in enumerate(segments)],
            "success_count": 0,
            "failed_count": 0,
            "final_video": None,   # ComfyUI 整段生成的最终视频（完成后填充）
            "_backed_up_count": sum(1 for v in initial_videos if "_old_video_path" in v),
            "_generating": True,   # 标记为生成中
            "_success": False      # 标记为未完成
        }
        if old_final_video:
            initial_data["_old_final_video"] = old_final_video  # 旧最终视频备份（恢复备份时回填）
        self.session_manager.save_step_result(session_id, step, initial_data, success=False)
        logger.info(f"[步骤4] 已写入生成中状态（备份 {initial_data['_backed_up_count']} 个旧视频）- 会话: {session_id[:8]}...")
        return initial_data

    def restore_videos_backup(self, session_id: str) -> dict:
        """恢复备份的视频（_old_video_path/_old_final_video 回填），返回恢复后的 result_data"""
        existing = self.session_manager.get_step_result(session_id, "generate_videos")
        if not existing:
            raise WorkflowError("未找到视频数据", status_code=404)

        result_data = existing["result_data"]
        if result_data.get("_generating"):
            raise WorkflowError("视频正在生成中，请先停止生成再恢复备份")
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

        # 旧最终视频一并恢复（mark_videos_generating 备份的 _old_final_video）；
        # 勾选与旧结果不相交时分段无备份（restored_count=0），但最终视频仍可恢复
        old_final = result_data.get("_old_final_video")
        if old_final:
            result_data["final_video"] = old_final

        if restored_count == 0 and not old_final:
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

        两段式链路优先消费 comfyui_import 暂存的工作流（导入 → 开始）；
        无暂存或勾选不一致时走一步式全流程（上传素材 → 构造 timeline → 整段提交）。
        远程不可用时 mock 本地合成演示视频。

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

        # 两段式链路：导入暂存与本次勾选一致时直接执行已注入的工作流
        imported = self._get_imported_state(session_id, segment_indexes)
        if imported is not None:
            return await self._execute_imported_videos(session_id, imported)

        return await self._step_generate_videos_comfyui(session_id, extra_prompt, segment_indexes)

    def _get_imported_state(self, session_id: str, segment_indexes: list[int] | None) -> dict | None:
        """读取与本次生成勾选一致的 comfyui_import 导入暂存（不存在/不一致返回 None）"""
        import_result = self.session_manager.get_step_result(session_id, "comfyui_import")
        if not import_result:
            return None
        data = import_result.get("result_data") or {}
        if not data.get("timeline_data"):
            return None
        if segment_indexes is not None and data.get("segment_indexes") != segment_indexes:
            logger.info("[步骤7] 导入暂存与本次勾选不一致，重新走全流程")
            return None
        return data

    def _auto_global_prompt(self, session_id: str) -> str:
        """用户未填全局提示词时，从剧本上下文自动生成本集戏剧基调（整条时间轴语境统一）。

        best-effort：任何异常都返回空串，绝不阻断主流程。
        """
        try:
            selected = self.get_selected_episode(session_id)
        except Exception:
            return ""
        script_session_id = selected.get("script_session_id", "")
        episode_id = selected.get("episode_id", "")
        parts: list[str] = []
        if script_session_id and episode_id:
            try:
                episode = self.store.get_episode(script_session_id, episode_id) or {}
            except Exception:
                episode = {}
            logline = (episode.get("logline") or "").strip()
            if logline:
                parts.append(f"本集剧情语境：{logline[:200]}")
        if script_session_id:
            try:
                logic = self.store.read_story_logic(script_session_id) or ""
            except Exception:
                logic = ""
            # [ \t]* 只吞同行空白（\s 会跨行吸入下一行正文）；截到首个句号，丢弃同行拖带的「主题内核」等后续字段
            m = re.search(r"情感基调与题材[：:][ \t]*(.+)", logic)
            if m and m.group(1).strip():
                tone = m.group(1).strip()
                tone = tone.split("。", 1)[0] + "。" if "。" in tone else tone
                parts.append(f"全剧基调：{tone[:150]}")
        if not parts:
            return ""
        parts.append("所有分镜共享以上语境，画面气质、光线情绪与节奏密度须与本集戏剧走向保持一致;")
        parts.append("任务对话标准语言为‘普通话’。")
        return "\n".join(parts)

    async def prepare_comfyui_import(
        self, session_id: str, segment_indexes: list[int] | None = None, global_prompt: str = "",
    ) -> dict:
        """阶段一（导入到 ComfyUI）：收集素材 → 上传+构造 timeline+注入工作流 → 暂存 → 返回摘要

        门禁与 mark_videos_generating 一致（分镜大纲完成 + ≥1 个分镜 configured）。
        global_prompt 为整条时间轴的全局提示词（timeline_data.globalPrompt）。
        段间重叠逐段取自分镜的 overlap 字段（第 3 步分镜管理配置，此处不再可覆盖）。
        暂存落在 step_results 的 comfyui_import 键（save_aux_state，不推进步骤状态机），
        「开始生成」时由后台任务消费。
        """
        logger.info(f"[步骤4] 导入到 ComfyUI - 会话: {session_id[:8]}...")
        if not self.session_manager.is_step_completed(session_id, "storyboard_outline"):
            raise WorkflowError("请先完成步骤2：分镜大纲")

        # 用户未填全局提示词时自动注入本集戏剧基调，避免逐段各唱各调
        if not global_prompt.strip():
            auto_prompt = self._auto_global_prompt(session_id)
            if auto_prompt:
                logger.info("[步骤4] 未填全局提示词，已自动注入本集戏剧基调")
                global_prompt = auto_prompt

        materials = self._collect_generation_materials(session_id, segment_indexes, gate=True)
        segments = materials["segments"]
        try:
            prepared = await self.comfyui_service.prepare_import(
                **materials, global_prompt=global_prompt,
                ui_workflow_name=f"导入_{session_id[:8]}.json",
            )
        except httpx.HTTPError as e:  # 连接失败/超时等网络异常
            raise WorkflowError(
                f"无法连接远程 ComfyUI（{COMFYUI_BASE_URL}），请检查隧道是否运行: ./start_comfyui_tunnel.sh（{e}）"
            )
        except ValueError as e:  # TimelineBuilder 校验失败等
            raise WorkflowError(f"导入到 ComfyUI 失败：{e}")

        timeline = prepared["timeline_data"]
        summary = {
            "segment_indexes": [s.get("index", i) for i, s in enumerate(segments)],
            "segment_count": len(segments),
            "image_count": len(timeline.get("images", [])),
            "audio_count": len(timeline.get("audios", [])),
            "total_duration": timeline.get("selection", {}).get("duration", 0),
            "global_prompt": global_prompt,
            "mock": prepared["mock"],
            "imported_at": datetime.now().isoformat(timespec="seconds"),
            # UI 工作流落盘结果（mock / 落盘失败时为 None）：ComfyUI 网页打开检查/微调用
            "ui_workflow_name": prepared.get("ui_workflow_name"),
            "comfyui_url": COMFYUI_BASE_URL,
        }
        self.session_manager.save_aux_state(session_id, "comfyui_import", {
            **summary,
            # 执行阶段消费：注入后的工作流 + timeline + 段内容（mock 渲染/结果回填）
            "workflow": prepared["workflow"],
            "timeline_data": timeline,
            "segments": [
                {"index": s.get("index", i), "content": s.get("content", "")}
                for i, s in enumerate(segments)
            ],
        })
        logger.info(
            f"[步骤4] 导入完成 - {summary['segment_count']} 段 / {summary['image_count']} 图 / "
            f"{summary['audio_count']} 音频 / 约 {summary['total_duration']}s, mock={summary['mock']}"
        )
        return summary

    async def _execute_imported_videos(self, session_id: str, imported: dict) -> dict:
        """阶段二（开始生成）：执行已导入的工作流并落盘结果"""
        logger.info(f"[步骤7][ComfyUI] 执行已导入工作流 - 会话: {session_id[:8]}...")
        try:
            result = await self.comfyui_service.execute_imported(
                imported.get("segments", []), imported.get("workflow"), imported["timeline_data"],
            )
            result_data = self._finalize_video_result(
                session_id, result, imported.get("segment_indexes", []),
            )
            mode_text = "（mock 演示视频）" if result.get("mock") else ""
            return {
                "success": True,
                "message": f"最终视频生成完成{mode_text}",
                "data": result_data,
            }
        except Exception as e:
            return self._save_video_failure(session_id, e)

    def _collect_generation_materials(
        self, session_id: str, segment_indexes: list[int] | None = None, *,
        extra_prompt: str = "", gate: bool = False,
    ) -> dict:
        """收集生成素材（两段式与一步式共用）：分镜子集、首帧图、参考图、音频"""
        frames_result = self.session_manager.get_step_result(session_id, "generate_segment_frames")

        segment_frames = frames_result['result_data'].get('segment_frames', []) if frames_result else []

        segments = self._resolve_generation_segments(session_id, segment_indexes, gate=gate)
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
            f"{len(audio_assets)} 个音频, 逐段overlap={[s.get('overlap', 0) for s in segments]}, "
            f"mock={self.comfyui_service.mock}"
        )
        return {
            "segments": segments,
            "frame_image_paths": frame_image_paths,
            "audio_assets": audio_assets,
            "reference_image_paths": reference_image_paths,
        }

    def _finalize_video_result(self, session_id: str, result: dict, seg_indexes: list[int]) -> dict:
        """构造成功结果并落盘（两段式与一步式共用）"""
        timeline = result["timeline_data"]
        result_data = {
            "generated_videos": [
                {
                    # 勾选子集时 timeline 段序对应过滤后 segments，回填原始分镜 index
                    "segment_index": seg_indexes[j] if j < len(seg_indexes) else j,
                    "video_id": result.get("prompt_id", ""),
                    "video_path": result["video_path"],
                    "duration": round((seg.get("endFrame", 0) - seg.get("startFrame", 0)) / timeline.get("fps", 24), 2),
                    "prompt": seg.get("prompt", ""),
                    "task_status": "completed",
                }
                for j, seg in enumerate(timeline["segmentConfig"]["segments"])
            ],
            "video_count": len(seg_indexes),
            "segment_indexes": seg_indexes,
            "success_count": len(seg_indexes),
            "failed_count": 0,
            "final_video": {
                "video_path": result["video_path"],
                "prompt_id": result.get("prompt_id", ""),
                "mock": result.get("mock", False),
                # 逐段重叠合计秒数（_overlap_seconds 为逐段列表；兼容旧结果的单值）
                "overlap_seconds": round(sum(
                    timeline.get("_overlap_seconds", [])
                    if isinstance(timeline.get("_overlap_seconds"), list)
                    else [timeline.get("_overlap_seconds", 0)]
                ), 3),
                "segment_count": len(seg_indexes),
            },
            "timeline_data": timeline,
            "_generating": False,
            "_success": True,
        }

        self.session_manager.save_step_result(session_id, "generate_videos", result_data)
        self.session_manager.update_session_status(session_id, "completed")

        mode_text = "（mock 演示视频）" if result.get("mock") else ""
        logger.info(f"[步骤7][ComfyUI] 完成 - 最终视频已生成{mode_text}: {result['video_path']}")
        return result_data

    def _save_video_failure(self, session_id: str, error: Exception) -> dict:
        """保存失败状态快照"""
        logger.error(f"[步骤7][ComfyUI] 失败: {str(error)}")
        failure_data = {
            "generated_videos": [],
            "video_count": 0,
            "success_count": 0,
            "failed_count": 1,
            "_generating": False,
            "_success": False,
            "error": str(error),
        }
        self.session_manager.save_step_result(session_id, "generate_videos", failure_data, success=False)
        return {"success": False, "error": f"视频生成失败: {str(error)}", "data": failure_data}

    async def _step_generate_videos_comfyui(
        self, session_id: str, extra_prompt: str = "", segment_indexes: list[int] | None = None,
    ) -> dict:
        """步骤7（ComfyUI 一步式链路）：上传材料 → 构造 timeline_data → 整段生成最终视频（勾选分镜子集拼接）"""
        logger.info(f"[步骤7][ComfyUI] 整段视频生成 - 会话: {session_id[:8]}...")

        try:
            # 只按 mark_videos_generating 落盘的 segment_indexes 过滤（不重跑门禁：
            # 生成期间取消某分镜 configured 不应中断任务）；异常走 except 落失败快照
            materials = self._collect_generation_materials(session_id, segment_indexes, extra_prompt=extra_prompt, gate=False)

            # 生成最终视频（mock 模式本地合成演示视频）；globalPrompt 用本集戏剧基调（一步式无用户填写入口）
            result = await self.comfyui_service.generate_full_video(
                **materials, global_prompt=self._auto_global_prompt(session_id),
            )

            seg_indexes = [s.get("index", i) for i, s in enumerate(materials["segments"])]
            result_data = self._finalize_video_result(session_id, result, seg_indexes)
            mode_text = "（mock 演示视频）" if result.get("mock") else ""
            return {
                "success": True,
                "message": f"最终视频生成完成{mode_text}",
                "data": result_data
            }

        except Exception as e:
            return self._save_video_failure(session_id, e)
