"""分镜工作流（视频工作流步骤 2/3）

2. storyboard_outline  分镜大纲：单次 agent run 产出 markmap 导图 + 分镜列表
3. segment_management  分镜管理：分镜形式/overlap 配置 + video-prompt skill 生成分镜提示词 + 显式完成

分镜配置与提示词统一存在 storyboard_outline.result_data.segments 中（单一数据源），
本模块通过 update_step_result 修改（不推进 current_step）。
"""
import logging
from datetime import datetime
from typing import Callable, Optional

from backend.core.agent_sdk import AgentEvent, run_agent
from backend.core.agent_sdk.wrapper import AgentRunOptions
from backend.core.models import StoryboardSegment, VideoParams
from backend.core.persistence import SessionManager
from backend.core.services.prompt_manager import get_prompt_manager
from backend.core.services.script_context_service import ScriptContextService
from backend.core.services.video_prompt_skill import load_video_prompt_skill
from backend.core.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)

OnEvent = Callable[[AgentEvent], None]

# 分镜形式（仅全能参考模式实现 overlap 与提示词生成关联逻辑）
VALID_SEGMENT_MODES = {"first_frame", "last_frame", "all_reference", "first_last_frame"}

MODE_LABELS = {
    "first_frame": "首帧模式",
    "last_frame": "尾帧模式",
    "all_reference": "全能参考模式",
    "first_last_frame": "首尾帧模式",
}


class StoryboardError(Exception):
    """分镜工作流业务错误（返回给前端 detail）"""


class StoryboardWorkflow:
    """分镜大纲生成与分镜管理"""

    def __init__(self, session_manager: SessionManager):
        self.sm = session_manager
        self.script_context = ScriptContextService()
        self.prompts = get_prompt_manager()

    # ==================== 通用 ====================

    def _get_selected(self, session_id: str) -> dict:
        """读取 select_episode 结果（script_session_id / episode_id / video_params）"""
        step = self.sm.get_step_result(session_id, "select_episode")
        if not step or not step.get("result_data"):
            raise StoryboardError("会话尚未完成第 1 步：从剧本选集")
        return step["result_data"]

    def _get_outline_data(self, session_id: str) -> dict:
        """读取 storyboard_outline result_data"""
        step = self.sm.get_step_result(session_id, "storyboard_outline")
        if not step or not step.get("result_data"):
            raise StoryboardError("分镜大纲尚未生成（第 2 步）")
        return step["result_data"]

    def _find_segment(self, data: dict, index: int) -> dict:
        seg = next((s for s in data.get("segments", []) if s.get("index") == index), None)
        if seg is None:
            raise StoryboardError(f"分镜 {index} 不存在")
        return seg

    def _load_story_outline(self, script_session_id: str) -> str:
        """读取剧本会话的全剧大纲（story_outline mindmap）"""
        from backend.deps import get_script_session_manager
        step = get_script_session_manager().get_step_result(script_session_id, "story_outline")
        return step["result_data"].get("mindmap", "") if step else ""

    # ==================== 第 2 步：分镜大纲 ====================

    async def generate_outline(
        self,
        session_id: str,
        extra_prompt: str = "",
        on_event: Optional[OnEvent] = None,
        interrupt: Optional[object] = None,
    ) -> dict:
        """生成分镜大纲（单次 agent run，产出导图 + 分镜列表）；重生成级联清下游"""
        can_execute, reason = self.sm.can_execute_step(session_id, "storyboard_outline")
        if not can_execute:
            raise StoryboardError(reason)

        selected = self._get_selected(session_id)
        video_params = VideoParams(**selected.get("video_params", {}))
        script_context = self.script_context.build_segment_script_context(
            selected["script_session_id"], selected["episode_id"],
        )

        user_prompt = self.prompts.render("storyboard_outline", {
            "video_params_context": video_params.to_prompt_context(),
            "script_context": script_context,
            "extra_instruction": f"\n\n## 用户额外要求\n{extra_prompt}\n请融入分镜切分。" if extra_prompt else "",
            "max_segment_duration": video_params.max_segment_duration,
        })
        system_prompt = "你是专业的视频分镜专家。严格按用户消息中的 JSON 格式输出，不要输出其他内容。"

        result = await run_agent(
            AgentRunOptions(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_turns=2,
                interrupt=interrupt,
            ),
            on_event or (lambda e: None),
        )
        if result.error:
            raise StoryboardError(f"分镜大纲生成失败: {result.error}")

        parsed = parse_json_response(result.text, default=None)
        if not isinstance(parsed, dict):
            raise StoryboardError("分镜大纲输出格式异常（未解析到 JSON），请重试")
        mindmap = (parsed.get("mindmap") or "").strip()
        if not mindmap or not mindmap.lstrip().startswith("#"):
            raise StoryboardError("分镜大纲输出格式异常（未得到 markdown 导图），请重试")

        raw_segments = [s for s in (parsed.get("segments") or []) if isinstance(s, dict)]
        if not raw_segments:
            raise StoryboardError("分镜大纲未产出分镜列表，请重试")

        # LLM 输出的 duration/overlap 不可信，解析后 clamp 到合法范围（首镜无上一分镜，overlap 固定 0）
        max_dur = video_params.max_segment_duration
        segments = []
        for i, s in enumerate(raw_segments):
            try:
                duration = int(s.get("duration", max_dur))
            except (TypeError, ValueError):
                duration = max_dur
            duration = max(5, min(duration, max_dur))
            try:
                overlap = int(s.get("overlap", 1))
            except (TypeError, ValueError):
                overlap = 1
            overlap = 0 if i == 0 else max(0, min(overlap, 3))
            segments.append(StoryboardSegment(
                index=i,
                title=str(s.get("title", "")),
                outline=str(s.get("outline", "")),
                duration=duration,
                overlap=overlap,
            ).model_dump())

        # 重生成 → 清下游（segment_management / generate_videos）；save 覆盖旧 segments（级联重置配置与提示词）
        self.sm.clear_steps_after(session_id, "storyboard_outline")
        self.sm.save_step_result(session_id, "storyboard_outline", {
            "mindmap": mindmap,
            "edited": False,
            "segments": segments,
            "segment_count": len(segments),
        }, success=True)
        logger.info(f"[分镜大纲] 会话 {session_id[:8]}... 生成分镜 {len(segments)} 个")
        return {"mindmap": mindmap, "segment_count": len(segments)}

    def update_outline(self, session_id: str, mindmap: str) -> dict:
        """人工编辑导图（只改 mindmap 与 edited 标记，不动 segments）"""
        if not mindmap.strip():
            raise StoryboardError("导图内容不能为空")
        data = self._get_outline_data(session_id)
        self.sm.update_step_result(session_id, "storyboard_outline", {
            **data, "mindmap": mindmap, "edited": True,
        })
        return {"mindmap": mindmap}

    # ==================== 第 3 步：分镜管理 ====================

    def update_segment_config(self, session_id: str, index: int, fields: dict) -> dict:
        """更新分镜配置（分镜形式 / overlap）

        mode 或 overlap 变化会清空该分镜已生成的提示词（提示词内嵌 overlap 语义）；
        若分镜管理已完成，则回退其完成状态（配置变化需重新确认）。
        """
        data = self._get_outline_data(session_id)
        seg = self._find_segment(data, index)

        mode = fields.get("mode")
        overlap = fields.get("overlap")
        if mode is not None:
            if mode not in VALID_SEGMENT_MODES:
                raise StoryboardError(f"非法的分镜形式: {mode}（可选: {', '.join(sorted(VALID_SEGMENT_MODES))}）")
            seg["mode"] = mode
        if overlap is not None:
            seg["overlap"] = int(overlap)

        # 提示词内嵌 overlap/mode 语义，配置变化后视为陈旧
        if mode is not None or overlap is not None:
            seg["prompt"] = ""

        self.sm.update_step_result(session_id, "storyboard_outline", data)

        if self.sm.is_step_completed(session_id, "segment_management"):
            self.sm.clear_step_result(session_id, "segment_management")
            self.sm.clear_steps_after(session_id, "segment_management")
            self.sm.reset_current_step(session_id, "segment_management")

        return {"segment": seg}

    def build_prompt_context(self, session_id: str, index: int) -> dict:
        """装配分镜提示词生成的上下文（弹窗展示与 agent 调用共用）"""
        selected = self._get_selected(session_id)
        data = self._get_outline_data(session_id)
        segments = data.get("segments", [])
        seg = self._find_segment(data, index)
        prev_seg = next((s for s in segments if s.get("index") == index - 1), None)

        # 生效 overlap：首个分镜无上一分镜，一律不承接
        overlap = int(seg.get("overlap", 1))
        effective_overlap = overlap if (index > 0 and seg.get("mode") == "all_reference") else 0

        if effective_overlap > 0:
            overlap_rule = (
                f"overlap={effective_overlap}：生成提示词时须承接上一分镜——开头加上「接续上一分镜」，"
                f"并写明上一分镜的结尾状态和本分镜的起始状态（两者有约 {effective_overlap} 秒的内容重叠过渡）"
            )
        else:
            overlap_rule = "不承接上一分镜（overlap=0 或首个分镜），提示词中不得出现「接续」字样"

        return {
            "episode_title": selected.get("episode_title", ""),
            "story_outline": self._load_story_outline(selected["script_session_id"]),
            "episode_context": self.script_context.build_segment_script_context(
                selected["script_session_id"], selected["episode_id"],
            ),
            "video_params": selected.get("video_params", {}),
            "segment": seg,
            "prev_segment": prev_seg,
            "overlap": overlap,
            "effective_overlap": effective_overlap,
            "overlap_rule": overlap_rule,
        }

    async def generate_segment_prompt(
        self,
        session_id: str,
        index: int,
        on_event: Optional[OnEvent] = None,
        interrupt: Optional[object] = None,
    ) -> dict:
        """用 video-prompt skill 规范 + 剧本上下文生成当前分镜的提示词（仅全能参考模式）"""
        can_execute, reason = self.sm.can_execute_step(session_id, "segment_management")
        if not can_execute:
            raise StoryboardError(reason)

        ctx = self.build_prompt_context(session_id, index)
        seg = ctx["segment"]
        if seg.get("mode") != "all_reference":
            raise StoryboardError("仅「全能参考模式」支持分镜提示词生成")

        segments_count = len(self._get_outline_data(session_id).get("segments", []))
        effective_overlap = ctx["effective_overlap"]
        prev_seg = ctx["prev_segment"]

        prev_section = ""
        if effective_overlap > 0 and prev_seg:
            prev_prompt = prev_seg.get("prompt") or "（尚未生成，仅参考大纲）"
            prev_section = (
                f"\n## 上一分镜（第 {index} 个）\n"
                f"标题：{prev_seg.get('title', '')}\n"
                f"大纲：{prev_seg.get('outline', '')}\n"
                f"已生成提示词：{prev_prompt}\n"
            )

        if effective_overlap > 0:
            rule = (
                f"- overlap={effective_overlap}：本分镜与上一分镜关联。提示词开头必须加上「接续上一分镜」字样，"
                f"且必须在提示词中明确写出上一分镜的结尾状态和本分镜的起始状态，"
                f"两个状态之间有约 {effective_overlap} 秒的内容重叠过渡"
            )
        else:
            rule = "- overlap=0：本分镜不承接上一分镜，提示词中不得出现「接续」「承接」等衔接字样"

        video_params = VideoParams(**ctx["video_params"])
        user_prompt = f"""## 提示词生成规范（必须完整遵循）
{load_video_prompt_skill()}

## 全剧大纲
{ctx['story_outline'] or '（无）'}

## 本集分集设计 / 脚本
{ctx['episode_context']}

## 视频参数
{video_params.to_prompt_context()}

## 当前分镜（第 {index + 1} 个，共 {segments_count} 个）
标题：{seg.get('title', '')}
大纲：{seg.get('outline', '')}
分镜形式：全能参考模式（all_reference）
建议时长：{seg.get('duration', '')} 秒
{prev_section}
## 分镜衔接规则
{rule}

## 输出要求
只输出本分镜的最终提示词文本（不要 JSON、不要解释、不要分镜表索引）。"""
        system_prompt = "你是专业的视频生成提示词工程师。严格遵循用户消息中的提示词生成规范，只输出最终提示词正文。"

        result = await run_agent(
            AgentRunOptions(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_turns=4,
                interrupt=interrupt,
            ),
            on_event or (lambda e: None),
        )
        if result.error:
            raise StoryboardError(f"分镜提示词生成失败: {result.error}")

        prompt_text = result.text.strip()
        if not prompt_text:
            raise StoryboardError("分镜提示词生成为空，请重试")

        data = self._get_outline_data(session_id)
        self._find_segment(data, index)["prompt"] = prompt_text
        self.sm.update_step_result(session_id, "storyboard_outline", data)
        logger.info(f"[分镜管理] 会话 {session_id[:8]}... 分镜 {index} 提示词已生成（{len(prompt_text)} 字）")
        return {"index": index, "prompt": prompt_text}

    def complete_segment_management(self, session_id: str) -> dict:
        """完成分镜配置（显式推进到第 4 步：视频生成）"""
        can_execute, reason = self.sm.can_execute_step(session_id, "segment_management")
        if not can_execute:
            raise StoryboardError(reason)

        data = self._get_outline_data(session_id)
        segments = data.get("segments", [])
        prompt_count = sum(1 for s in segments if s.get("prompt"))

        # 重做时先清掉视频生成结果
        self.sm.clear_steps_after(session_id, "segment_management")
        self.sm.save_step_result(session_id, "segment_management", {
            "completed_at": datetime.now().isoformat(),
            "segment_count": len(segments),
            "prompt_count": prompt_count,
        }, success=True)
        logger.info(f"[分镜管理] 会话 {session_id[:8]}... 分镜配置完成（{len(segments)} 个分镜，{prompt_count} 个提示词）")
        return {"segment_count": len(segments), "prompt_count": prompt_count}
