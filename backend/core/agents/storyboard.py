"""分镜工作流（视频工作流步骤 2/3）

2. storyboard_outline  分镜大纲：agent 在剧本工作区内自主检索（Read/Grep/Glob）
                        产出 markmap 导图 + 分镜列表
3. segment_management  分镜管理：分镜形式/overlap 配置 + 参考素材图管理
                        + video-prompt skill 生成分镜提示词 + 显式完成

分镜产物以 markdown 文件存于剧本工作区 04-storyboards/{ep}/vs-{会话}/ 下
（storyboard.md 导图 + seg_NN 单镜文件，权威源为 WorkspaceStore）；
DB step_results 只保留薄 envelope 与完成态标志。
"""
import logging
import re
import threading
from typing import Optional

from backend.core.agent_sdk import AgentEvent
from backend.core.agents.system_prompts import (
    MATERIAL_GENERATE_SYSTEM,
    SEGMENT_PROMPT_SYSTEM,
    SEGMENT_REF_MATCH_SYSTEM,
    STORYBOARD_OUTLINE_SYSTEM,
)
from backend.core.agents.workflow_base import OnEvent, StepWorkflowBase
from backend.core.errors import WorkflowError
from backend.core.models import StoryboardSegment, VideoParams
from backend.core.persistence import SessionManager
from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.workspace_store import WorkspaceStore
from backend.core.services.agent_step_service import AgentStepService
from backend.core.services.image_service import build_image_service_from_model_config
from backend.core.services.image_task_service import ImageTaskService, ImageTaskSpec
from backend.core.services.material_pool_service import MaterialPoolService
from backend.core.services.script_context_service import ScriptContextService
from backend.core.services.video_prompt_skill import sync_video_prompt_skill
from backend.core.services.workspace_sections import (
    get_selected_episode,
    load_story_outline,
    workspace_envelope,
    workspace_section,
)
from backend.core.utils.image_store import archive_generated_image
from backend.core.utils.image_utils import ensure_agent_thumbnail
from backend.core.utils.json_parser import is_valid_mindmap, parse_json_response
from backend.core.utils.path_utils import resolve_project_path

logger = logging.getLogger(__name__)

# 分镜形式（仅全能参考模式实现 overlap 与提示词生成关联逻辑）
VALID_SEGMENT_MODES = {"first_frame", "last_frame", "all_reference", "first_last_frame"}

MODE_LABELS = {
    "first_frame": "首帧模式",
    "last_frame": "尾帧模式",
    "all_reference": "全能参考模式",
    "first_last_frame": "首尾帧模式",
}


class StoryboardError(WorkflowError):
    """分镜工作流业务错误（返回给前端 detail；status_code 供全局异常 handler 使用）"""


class StoryboardWorkflow(StepWorkflowBase):
    """分镜大纲生成与分镜管理"""

    Error = StoryboardError

    # 自动匹配参考图上限：提示词通常涉及 1-4 个主体/场景，与生图参考上限（OpenAI edits 协议 4 张）一致；
    # 手动关联的 schema 上限（8 张）不受影响
    MAX_AUTO_MATCH_REFS = 4

    def __init__(
        self,
        session_manager: SessionManager,
        store: WorkspaceStore,
        script_manager: Optional[ScriptManager] = None,
    ):
        super().__init__(session_manager)
        self.store = store
        scm = script_manager or ScriptManager()
        self.script_context = ScriptContextService(script_manager=scm, store=store)
        # 素材池装配 / agent 步骤运行封装 / 生图任务状态机（业务异常统一为 StoryboardError）
        self.materials = MaterialPoolService(store, scm, StoryboardError)
        self.agent_steps = AgentStepService(StoryboardError)
        self.image_tasks = ImageTaskService(StoryboardError)
        # 会话级 segments 写锁（配置/参考图/提示词收尾并发写分镜文件时防 lost update）
        self._seg_locks: dict[str, threading.Lock] = {}
        self._seg_locks_guard = threading.Lock()

    def _segment_lock(self, session_id: str) -> threading.Lock:
        with self._seg_locks_guard:
            lock = self._seg_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._seg_locks[session_id] = lock
            return lock

    # ==================== 通用 ====================

    def _get_selected(self, session_id: str) -> dict:
        """读取 select_episode 结果（script_session_id / episode_id / video_params）"""
        return get_selected_episode(self.sm, session_id)

    def _storyboard_loc(self, session_id: str) -> tuple[str, str]:
        """(script_session_id, episode_id)：分镜文件的定位三元组前两元"""
        selected = self._get_selected(session_id)
        return selected["script_session_id"], selected["episode_id"]

    def _get_outline_data(self, session_id: str) -> dict:
        """读取分镜大纲（工作区文件权威源；DB 行只留薄 envelope）"""
        script_session_id, episode_id = self._storyboard_loc(session_id)
        data = self.store.read_storyboard(script_session_id, episode_id, session_id)
        if not data:
            raise StoryboardError(
                "分镜大纲尚未生成（第 2 步）", status_code=400,
            )
        return data

    def _storyboard_envelope(self, session_id: str) -> dict:
        """分镜步骤薄 envelope（path 为相对项目根的 workspace/... 路径，与剧本侧一致）"""
        script_session_id, episode_id = self._storyboard_loc(session_id)
        story = self.store.story_dir(script_session_id)
        vs_dir = self.store.storyboard_dir(script_session_id, episode_id, session_id)
        rel = vs_dir.relative_to(story).as_posix() + "/storyboard.md" if story else ""
        return workspace_envelope(self.store, script_session_id, rel) if rel else {"_artifact": "workspace", "path": ""}

    def _find_segment(self, data: dict, index: int) -> dict:
        seg = next((s for s in data.get("segments", []) if s.get("index") == index), None)
        if seg is None:
            raise StoryboardError(f"分镜 {index} 不存在")
        return seg

    async def generate_outline(
        self,
        session_id: str,
        extra_prompt: str = "",
        on_event: Optional[OnEvent] = None,
        interrupt: Optional[object] = None,
    ) -> dict:
        """生成分镜大纲（单次 agent run，产出导图 + 分镜列表）；重生成级联清下游"""
        self.ensure_can_execute(session_id, "storyboard_outline")

        selected = self._get_selected(session_id)
        video_params = VideoParams(**selected.get("video_params", {}))
        script_session_id = selected["script_session_id"]

        def _parse_outline(text: str) -> dict:
            try:
                parsed = parse_json_response(text, default=None)
            except ValueError:  # default=None 时空文本/非 JSON 抛异常而非返回 None
                parsed = None
            if not isinstance(parsed, dict):
                raise StoryboardError("分镜大纲输出格式异常（未解析到 JSON），请重试")
            mindmap = (parsed.get("mindmap") or "").strip()
            if not is_valid_mindmap(mindmap):
                raise StoryboardError("分镜大纲输出格式异常（未得到 markdown 导图），请重试")
            if not [s for s in (parsed.get("segments") or []) if isinstance(s, dict)]:
                raise StoryboardError("分镜大纲未产出分镜列表，请重试")
            return parsed

        parsed = await self.agent_steps.run(
            "分镜大纲生成",
            template="storyboard_outline",
            variables={
                "video_params_context": video_params.to_prompt_context(),
                "workspace_section": workspace_section(self.store, script_session_id, selected["episode_id"]),
                "extra_instruction": f"\n\n## 用户额外要求\n{extra_prompt}\n请融入分镜切分。" if extra_prompt else "",
                "max_segment_duration": video_params.max_segment_duration,
            },
            system_prompt=STORYBOARD_OUTLINE_SYSTEM,
            # 剧本目录内自主检索（Read/Grep/Glob），留足检索轮次后输出 JSON
            cwd=self.store.story_cwd(script_session_id),
            max_turns=12,
            interrupt=interrupt,
            on_event=on_event,
            parse=_parse_outline,
        )
        mindmap = (parsed.get("mindmap") or "").strip()
        raw_segments = [s for s in (parsed.get("segments") or []) if isinstance(s, dict)]

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

        # 重生成 → 清下游（segment_management / generate_videos）；write_storyboard 清目录重写（级联重置配置与提示词）
        self.sm.clear_steps_after(session_id, "storyboard_outline")
        script_session_id, episode_id = self._storyboard_loc(session_id)
        self.store.write_storyboard(script_session_id, episode_id, session_id, mindmap, segments)
        self.sm.save_step_result(session_id, "storyboard_outline",
                                 self._storyboard_envelope(session_id), success=True)
        logger.info(f"[分镜大纲] 会话 {session_id[:8]}... 生成分镜 {len(segments)} 个")
        return {"mindmap": mindmap, "segment_count": len(segments)}

    def update_outline(self, session_id: str, markdown: str) -> dict:
        """人工编辑导图（markdown 含 `- 分镜内容` 行），解析后同步 mindmap 与 segments

        - `### 标题` 行界定分镜，其后至下一标题行之间的 `- ` 列表行合并为该分镜 outline
        - 其余 `- ` 行（不属于任何分镜）原样保留在 mindmap 中
        - title/outline 有变化或分镜增删时：变化分镜清空已生成提示词，
          若分镜管理已完成则回退其完成状态（变化需重新确认）
        """
        if not markdown.strip():
            raise StoryboardError("导图内容不能为空")
        lines = markdown.strip().split("\n")
        if not is_valid_mindmap(markdown):
            raise StoryboardError("导图内容格式异常（需以 # 标题开头）")

        # 解析分镜标题与归属的内容行（outline_lines 记录行号，便于剔除后还原 mindmap）
        # 标题匹配用 `### ` 前缀（与前端 /^###\s/ 一致；#### 更深层级不构成分镜）
        outline_lines: set[int] = set()
        parsed: list[dict] = []
        current: Optional[dict] = None
        for idx, raw in enumerate(lines):
            line = raw.rstrip()
            if _SEGMENT_HEADING.match(line):
                current = {"title": line.lstrip("#").strip(), "outline": ""}
                parsed.append(current)
            elif line.startswith("#"):
                current = None
            elif current is not None and line.lstrip().startswith("-"):
                text = line.lstrip()[1:].strip()
                current["outline"] = f"{current['outline']} {text}".strip()
                outline_lines.add(idx)
        if not parsed:
            raise StoryboardError("导图中未找到分镜（### 层级），请检查格式")

        stored_mindmap = "\n".join(l for i, l in enumerate(lines) if i not in outline_lines)

        # 与旧 segments 按 title 匹配合并（按下标配对会在中间增删分镜时整体错位）
        with self._segment_lock(session_id):
            data = self._get_outline_data(session_id)
            old_segments = data.get("segments", [])
            max_dur = VideoParams(**self._get_selected(session_id).get("video_params", {})).max_segment_duration
            old_by_title: dict[str, list[dict]] = {}
            for old in old_segments:
                old_by_title.setdefault(str(old.get("title", "")), []).append(old)

            changed = len(parsed) != len(old_segments)
            segments = []
            for i, p in enumerate(parsed):
                # 同名分镜按顺序消费（重名场景按出现顺序对应）
                candidates = old_by_title.get(p["title"], [])
                old = candidates.pop(0) if candidates else None
                if old and _norm_ws(old.get("outline", "")) == _norm_ws(p["outline"]):
                    old["index"] = i  # 位置变化时重排（title 匹配保留的旧 index 可能已错位）
                    segments.append(old)
                    continue
                changed = True
                if old:
                    segments.append({**old, "title": p["title"], "outline": p["outline"], "prompt": "", "configured": False})
                else:  # 编辑新增的分镜：默认时长/overlap，提示词为空
                    segments.append(StoryboardSegment(
                        index=i, title=p["title"], outline=p["outline"],
                        duration=max_dur, overlap=1 if i > 0 else 0,
                    ).model_dump())
                segments[-1]["index"] = i  # title 匹配保留的旧分镜 index 已错位，统一重排

            # 统一次序：先写文件（权威源）成功，再回退 DB 完成态与 envelope——
            # 中途失败时文件为准、DB 完成态可安全重试（与 _save_segment_change 一致）
            script_session_id, episode_id = self._storyboard_loc(session_id)
            self.store.replace_storyboard(
                script_session_id, episode_id, session_id,
                mindmap=stored_mindmap, segments=segments, edited=True,
            )
            self.sm.update_step_result(session_id, "storyboard_outline",
                                       self._storyboard_envelope(session_id))
        logger.info(f"[分镜大纲] 会话 {session_id[:8]}... 人工编辑导图（{len(segments)} 个分镜，变化: {changed}）")
        return {"mindmap": stored_mindmap, "segment_count": len(segments)}

    # ==================== 第 3 步：分镜管理 ====================

    def _save_segment_change(self, session_id: str, index: int, seg_fields: dict, *, stale_prompt: bool) -> dict:
        """分镜变化统一收尾：单文件写回；配置变化时清提示词并回退该分镜的 configured 完成态"""
        if stale_prompt:
            seg_fields["prompt"] = ""
            seg_fields["configured"] = False
        script_session_id, episode_id = self._storyboard_loc(session_id)
        seg = self.store.update_segment_fields(
            script_session_id, episode_id, session_id, index, seg_fields,
        )
        return seg

    def update_segment_config(self, session_id: str, index: int, fields: dict) -> dict:
        """更新分镜配置（分镜形式 / overlap）

        mode 或 overlap 真实变化（与现值不同）才清空该分镜已生成的提示词
        （提示词内嵌 overlap 语义；幂等写不清空）；若分镜管理已完成，则回退其
        完成状态（配置变化需重新确认）。
        """
        with self._segment_lock(session_id):
            seg = self._find_segment(self._get_outline_data(session_id), index)  # 存在性校验

            mode = fields.get("mode")
            overlap = fields.get("overlap")
            if mode is not None:
                if mode not in VALID_SEGMENT_MODES:
                    raise StoryboardError(f"非法的分镜形式: {mode}（可选: {', '.join(sorted(VALID_SEGMENT_MODES))}）")
            seg_fields = {k: v for k, v in (("mode", mode), ("overlap", overlap)) if v is not None}
            if overlap is not None:
                seg_fields["overlap"] = int(overlap)

            changed = (
                (mode is not None and mode != seg.get("mode"))
                or (overlap is not None and int(overlap) != seg.get("overlap"))
            )
            seg = self._save_segment_change(session_id, index, seg_fields, stale_prompt=changed)

        return {"segment": seg}

    # ==================== 第 3 步：分镜参考素材图 ====================

    def list_material_pool(self, session_id: str) -> dict:
        """选择弹窗素材池：定妆照（story 级）+ 本集素材 + 其他集素材（不跨 story）"""
        selected = self._get_selected(session_id)
        return self.materials.list_pool(selected["script_session_id"], selected["episode_id"])

    def delete_material(self, script_session_id: str, image_id: str) -> bool:
        """删除分集素材图（素材池记录 + 磁盘归档文件）"""
        return self.materials.delete_material(script_session_id, image_id)

    def update_segment_reference_images(self, session_id: str, index: int, items: list[dict]) -> dict:
        """保存分镜参考素材图（全量覆盖，仅全能参考模式）

        description 为空时带出库内描述；image_path 总是从素材源刷新（防陈旧路径）。
        图片集合变化（增/删/换图）会清空该分镜已生成的提示词并回退分镜管理完成态；
        仅编辑描述不影响。
        """
        selected = self._get_selected(session_id)
        with self._segment_lock(session_id):
            seg = self._find_segment(self._get_outline_data(session_id), index)
            if seg.get("mode") != "all_reference":
                raise StoryboardError("请先将分镜形式切换为「全能参考模式」再编辑参考图")

            resolved: list[dict] = []
            seen: set[str] = set()
            for item in items:
                image_id = item.get("image_id", "")
                if not image_id or image_id in seen:
                    continue
                seen.add(image_id)
                pool = self.materials.resolve_pool_image(selected["script_session_id"], image_id)
                resolved.append({
                    "image_id": image_id,
                    "image_path": pool["image_path"],
                    "description": (item.get("description") or "").strip() or pool["description"],
                })

            old_ids = {r.get("image_id") for r in seg.get("reference_images", [])}
            stale_prompt = old_ids != seen
            seg = self._save_segment_change(
                session_id, index, {"reference_images": resolved}, stale_prompt=stale_prompt,
            )

        logger.info(f"[分镜管理] 会话 {session_id[:8]}... 分镜 {index} 参考图已保存（{len(resolved)} 张，图片集合变化: {stale_prompt}）")
        return {"segment": seg}

    def validate_segment_material_request(
        self,
        session_id: str,
        index: int,
        user_prompt: str,
        mentioned_image_ids: list[str],
        reference_paths: list[str],
    ) -> tuple[dict, list[dict], list[str]]:
        """AI 生成素材图的前置校验（API 层 fail fast 与 agent run 内共用）

        Returns:
            (selected, @引用素材解析结果, 上传参考图路径列表)
        """
        selected = self._get_selected(session_id)
        data = self._get_outline_data(session_id)
        seg = self._find_segment(data, index)
        if seg.get("mode") != "all_reference":
            raise StoryboardError("请先将分镜形式切换为「全能参考模式」再生成素材图")

        user_prompt = (user_prompt or "").strip()
        mentioned_image_ids = [i for i in (mentioned_image_ids or []) if i]
        reference_paths = [p for p in (reference_paths or []) if p]
        if not user_prompt and not mentioned_image_ids and not reference_paths:
            raise StoryboardError("请填写提示词，或提供参考图（@ 素材图 / 上传参考图）")

        mentioned = [self.materials.resolve_pool_image(selected["script_session_id"], i) for i in mentioned_image_ids]
        reference_paths = self.materials.validate_reference_paths(reference_paths)
        return selected, mentioned, reference_paths

    async def generate_segment_material(
        self,
        session_id: str,
        index: int,
        user_prompt: str = "",
        mentioned_image_ids: list[str] | None = None,
        reference_paths: list[str] | None = None,
        model_config_id: str | None = None,
        on_event: Optional[OnEvent] = None,
        interrupt: Optional[object] = None,
    ) -> dict:
        """AI 生成分镜素材图（单次 agent run）：

        LLM 需求理解（剧本/本集/分镜上下文 + @素材 + 上传参考图 + 自定义提示词 → 生图 prompt 与描述）
        → 生图 → 归档 static/images/{story_name}/{episode_name}/ → 登记素材池 → 自动关联当前分镜
        """
        self.ensure_can_execute(session_id, "segment_management")
        selected, mentioned, reference_paths = self.validate_segment_material_request(
            session_id, index, user_prompt, mentioned_image_ids or [], reference_paths or [],
        )
        script_session_id = selected["script_session_id"]
        episode_id = selected["episode_id"]

        # 生图参考图 = @素材 + 上传图（OpenAI edits 协议上限 4 张）
        gen_refs = [m["image_path"] for m in mentioned] + list(reference_paths)
        if len(gen_refs) > 4:
            logger.warning(f"[素材生成] 参考图 {len(gen_refs)} 张超过上限，截断为 4 张")
            gen_refs = gen_refs[:4]

        # 1. LLM 需求理解（工作区路径 + 分镜上下文；Agent 可在剧本目录内自主检索）
        ctx = self.build_prompt_context(session_id, index)
        seg = ctx["segment"]

        def _parse_material(text: str) -> dict:
            try:
                item = parse_json_response(text, default=None)
            except ValueError:  # default=None 时空文本/非 JSON 抛异常而非返回 None
                item = None
            if not isinstance(item, dict) or not (item.get("image_prompt") or "").strip():
                raise StoryboardError("素材图需求理解输出格式异常（未解析到 JSON），请重试")
            return item

        on_event(AgentEvent(type="thinking", delta="正在理解素材图需求..."))
        item = await self.agent_steps.run(
            "素材图需求理解",
            template="material_generate",
            variables={
                "workspace_section": workspace_section(self.store, script_session_id, episode_id),
                "segment_context": (
                    f"标题：{seg.get('title', '')}\n大纲：{seg.get('outline', '')}\n建议时长：{seg.get('duration', '')} 秒"
                ),
                "mentioned_images": "\n".join(
                    f"- {m['image_id']}《{m['description'] or '（无描述）'}》{_ref_abs_path(m['image_path'])}" for m in mentioned
                ) or "（无）",
                "uploaded_refs": "\n".join(f"- {p}" for p in reference_paths) or "（无）",
                "user_prompt": (user_prompt or "").strip() or "（无自定义要求，按分镜内容自由发挥）",
            },
            system_prompt=MATERIAL_GENERATE_SYSTEM,
            cwd=self.store.story_cwd(script_session_id),
            max_turns=8,
            interrupt=interrupt,
            on_event=on_event,
            parse=_parse_material,
        )
        title = (item.get("title") or "").strip() or f"分镜素材{index + 1}"
        description = (item.get("description") or "").strip() or title
        image_prompt = item["image_prompt"].strip()

        # 2. 登记素材池（pending，仿定妆照状态机）
        scm = self.script_context.scm
        row = scm.insert_episode_material(
            script_session_id, episode_id, title=title, description=description,
            prompt=image_prompt, task_status="pending",
            meta={"origin": "ai", "segment_index": index, "user_prompt": (user_prompt or "").strip()},
        )
        mat_id = row["image_id"]

        # 3. 生图（OpenAI 协议：提交即同步完成，poll 取回缓存结果）+ 归档图库
        #    static/images/{story_name}/{episode_name}/（归档钩子回写 image_path/meta）
        image_service = build_image_service_from_model_config(model_config_id)
        video_params = VideoParams(**selected.get("video_params", {}))
        story_name = self.store.story_title(script_session_id) or f"story_{script_session_id[:8]}"
        episode_name = selected.get("episode_title") or episode_id

        archived: dict[str, str] = {}

        async def _archive(image_id: str, poll: dict) -> dict:
            image_path = await archive_generated_image(
                poll["image_url"], story_name, episode_name, title, image_id,
            )
            archived["image_path"] = image_path
            return {
                "image_path": image_path,
                "meta": {"origin": "ai", "segment_index": index, "user_prompt": (user_prompt or "").strip(),
                         "archived": not image_path.startswith("http")},
            }

        on_event(AgentEvent(type="thinking", delta="素材图生成中..."))
        poll = await self.image_tasks.run_single(
            image_service,
            ImageTaskSpec(image_id=mat_id, prompt=image_prompt, reference_paths=gen_refs or None),
            video_params,
            scm.update_episode_material,
            label="素材图",
            poll_timeout=150,
            poll_interval=3,
            interrupt=interrupt,
            on_completed=_archive,
        )
        image_path = archived.get("image_path", poll.get("image_url", ""))

        # 4. 自动关联当前分镜（锁内重读，防 lost update）
        with self._segment_lock(session_id):
            seg = self._find_segment(self._get_outline_data(session_id), index)
            refs = list(seg.get("reference_images") or [])
            if all(r.get("image_id") != mat_id for r in refs):
                refs.append({"image_id": mat_id, "image_path": image_path, "description": description})
            self._save_segment_change(
                session_id, index, {"reference_images": refs}, stale_prompt=True,
            )

        logger.info(
            f"[素材生成] 会话 {session_id[:8]}... 分镜 {index} 素材 {mat_id}《{title}》完成 → {image_path}"
        )
        return {"image_id": mat_id, "title": title, "image_path": image_path, "description": description}

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
            "story_outline": load_story_outline(self.store, selected["script_session_id"]),
            "episode_context": self.script_context.build_segment_script_context(
                selected["script_session_id"], selected["episode_id"],
            ),
            "video_params": selected.get("video_params", {}),
            "segment": seg,
            "prev_segment": prev_seg,
            "reference_images": seg.get("reference_images", []),
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
        self.ensure_can_execute(session_id, "segment_management")

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
            prev_path = self.store.segment_path(*self._storyboard_loc(session_id), session_id, index - 1)
            prev_section = (
                f"\n## 上一分镜（第 {index} 个）\n"
                f"文件：{prev_path or '（无）'}\n"
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

        reference_images = ctx.get("reference_images") or []
        if reference_images:
            ref_lines = "\n".join(
                f"- {r.get('image_id', '')}《{r.get('description', '') or '（无描述）'}》{_ref_abs_path(r.get('image_path', ''))}"
                for r in reference_images
            )
            reference_section = (
                f"\n## 本分镜参考素材图（生成视频时将以这些图为全能参考，提示词须结合其画面内容；"
                f"本地图片可直接 Read 查看画面）\n{ref_lines}\n"
            )
        else:
            reference_section = "\n## 本分镜参考素材图\n（无素材图）\n"

        script_session_id, episode_id = self._storyboard_loc(session_id)
        seg_path = self.store.segment_path(script_session_id, episode_id, session_id, index)
        episode_path = self.store.episode_path(script_session_id, episode_id)

        # 渐进式披露：skill 规范全文同步进工作区，prompt 只留必读指引
        story_root = self.store.story_dir(script_session_id)
        skill_rel = sync_video_prompt_skill(story_root).relative_to(story_root).as_posix()

        user_prompt = f"""## 提示词生成规范（必读，完整遵循）
目录：{skill_rel}/
1. 先 Read {skill_rel}/SKILL.md（总体流程与规范）
2. 再依次 Read {skill_rel}/references/ 下 scene-expansion.md、cinematic-script.md、shot-and-sound.md

## 剧本工作区（你只可在该目录内使用 Read/Grep/Glob 自主检索，禁止越界）
{workspace_section(self.store, script_session_id, episode_id)}

## 视频参数
{video_params.to_prompt_context()}

## 当前分镜（第 {index + 1} 个，共 {segments_count} 个）
文件：{seg_path or '（无）'}
标题：{seg.get('title', '')}
大纲：{seg.get('outline', '')}
分镜形式：全能参考模式（all_reference）
建议时长：{seg.get('duration', '')} 秒
{prev_section}{reference_section}
## 分镜衔接规则
{rule}

## 检索指引（按需，不强制）
- 必读本集分集设计：{episode_path or '01-outline 与 02-episodes 目录'}（梗概/矛盾链/因果链/结尾摘要）
- 本集 frontmatter 的 character_ids/scene_ids 指向实体卡：需要人物外观细节或内在动机时 Read 对应 03-entities/ 文件
- 追某伏笔/线索的跨集动作：Grep 该实体 ID（如 fs_001）
- 全剧主线与前后集衔接：01-outline/outline.md 与 02-episodes/ 相邻集文件

## 输出要求
只输出本分镜的最终提示词文本（不要 JSON、不要解释、不要分镜表索引）。"""
        system_prompt = SEGMENT_PROMPT_SYSTEM

        def _parse_prompt(text: str) -> str:
            prompt_text = text.strip()
            if not prompt_text:
                raise StoryboardError("分镜提示词生成为空，请重试")
            return prompt_text

        # 剧本目录内自主检索 + 必读 skill 规范文件，留足 Read 轮次
        prompt_text = await self.agent_steps.run(
            "分镜提示词生成",
            prompt=user_prompt,
            system_prompt=system_prompt,
            cwd=self.store.story_cwd(script_session_id),
            max_turns=16,
            interrupt=interrupt,
            on_event=on_event,
            parse=_parse_prompt,
        )

        with self._segment_lock(session_id):
            script_session_id, episode_id = self._storyboard_loc(session_id)
            seg = self.store.update_segment_fields(
                script_session_id, episode_id, session_id, index, {"prompt": prompt_text},
            )

        # 第二阶段：进入本 run 时无参考图 → 按刚生成的提示词自动匹配（失败不阻断已落盘的提示词）
        match = {"status": "skipped", "image_ids": []}
        if not reference_images:
            match = await self._auto_match_reference_images(
                session_id, index, prompt_text, on_event=on_event, interrupt=interrupt,
            )

        logger.info(
            f"[分镜管理] 会话 {session_id[:8]}... 分镜 {index} 提示词已生成（{len(prompt_text)} 字，"
            f"参考图自动匹配: {match['status']} {len(match['image_ids'])} 张）"
        )
        return {
            "index": index,
            "prompt": prompt_text,
            "match_status": match["status"],
            "matched_image_ids": match["image_ids"],
        }

    async def _auto_match_reference_images(
        self,
        session_id: str,
        index: int,
        prompt_text: str,
        on_event: Optional[OnEvent] = None,
        interrupt: Optional[object] = None,
    ) -> dict:
        """提示词生成后的第二阶段：从素材池自动匹配参考图（轻量 agent run）

        候选范围 = 素材池「核心素材」（lookbook 定妆照）+「本集素材」，不含其他集；
        图是按刚生成的提示词挑的 → 写入时 stale_prompt=False（与手动换图清提示词的联动相反）。
        任何失败仅记日志/thinking 提示，不抛错（提示词已保存，绝不阻断主流程）。

        Returns:
            {"status": matched|no_match|empty_pool|skipped|failed, "image_ids": [...]}
        """
        def _emit(delta: str) -> None:
            if on_event:
                on_event(AgentEvent(type="thinking", delta=delta))

        try:
            script_session_id, episode_id = self._storyboard_loc(session_id)

            # 1. 候选清单（仅 lookbook + current 组；池空直接跳过）
            pool = self.materials.list_pool(script_session_id, episode_id)
            candidates = [
                m for g in pool.get("groups", [])
                if g.get("key") in ("lookbook", "current")
                for m in g.get("materials", [])
            ]
            if not candidates:
                logger.info(f"[分镜管理] 会话 {session_id[:8]}... 分镜 {index} 素材池无候选，跳过自动匹配")
                return {"status": "empty_pool", "image_ids": []}

            seg = self._find_segment(self._get_outline_data(session_id), index)
            segment_context = (
                f"标题：{seg.get('title', '')}\n大纲：{seg.get('outline', '')}\n建议时长：{seg.get('duration', '')} 秒"
            )
            candidate_lines = "\n".join(
                f"- {m['image_id']}《{(m.get('title') + '：') if m.get('title') else ''}"
                f"{m.get('description') or '（无描述）'}》{_ref_abs_path(m['image_path'])}"
                for m in candidates
            )

            def _parse_match(text: str) -> list[str]:
                try:
                    parsed = parse_json_response(text, default=None)
                except ValueError:  # default=None 时空文本/非 JSON 抛异常而非返回 None
                    parsed = None
                ids = parsed.get("image_ids") if isinstance(parsed, dict) else None
                if not isinstance(ids, list):  # 空数组合法（宁缺毋滥），非 list 才算格式异常
                    raise StoryboardError("参考图匹配输出格式异常（未解析到 image_ids 列表）")
                return [i for i in ids if isinstance(i, str)]

            # 2. 轻量 agent run：LLM 可 Read 候选缩略图看画面（cwd 授予只读工具）
            _emit("\n正在从素材池自动匹配参考素材图...\n")
            image_ids = await self.agent_steps.run(
                "参考素材图匹配",
                template="segment_material_match",
                variables={
                    "segment_context": segment_context,
                    "segment_prompt": prompt_text,
                    "candidate_images": candidate_lines,
                    "max_images": self.MAX_AUTO_MATCH_REFS,
                },
                system_prompt=SEGMENT_REF_MATCH_SYSTEM,
                cwd=self.store.story_cwd(script_session_id),
                max_turns=12,
                interrupt=interrupt,
                on_event=on_event,
                parse=_parse_match,
            )

            # 3. 校验收敛：过滤候选外 ID（防幻觉）→ 保序去重 → resolve（中途被删则跳过）→ 截断上限
            valid_ids = {m["image_id"] for m in candidates}
            picked = [i for i in dict.fromkeys(image_ids) if i in valid_ids]
            if len(picked) > self.MAX_AUTO_MATCH_REFS:
                logger.warning(f"[分镜管理] 匹配 {len(picked)} 张超上限，截断为 {self.MAX_AUTO_MATCH_REFS}")
                picked = picked[:self.MAX_AUTO_MATCH_REFS]
            resolved = []
            for image_id in picked:
                try:
                    row = self.materials.resolve_pool_image(script_session_id, image_id)
                except StoryboardError:
                    logger.warning(f"[分镜管理] 匹配结果 {image_id} 解析失败，跳过")
                    continue
                resolved.append({
                    "image_id": image_id,
                    "image_path": row["image_path"],
                    "description": row["description"],
                })

            # 4. 锁内重读后写入：run 期间用户手动关联了参考图 → 不覆盖；stale_prompt=False 保留提示词
            with self._segment_lock(session_id):
                seg = self._find_segment(self._get_outline_data(session_id), index)
                if seg.get("reference_images"):
                    logger.info(f"[分镜管理] 会话 {session_id[:8]}... 分镜 {index} 已有参考图，跳过自动匹配写入")
                    return {"status": "skipped", "image_ids": []}
                if resolved:
                    self._save_segment_change(
                        session_id, index, {"reference_images": resolved}, stale_prompt=False,
                    )

            status = "matched" if resolved else "no_match"
            if resolved:
                _emit(f"\n已自动匹配 {len(resolved)} 张参考素材图（{', '.join(r['image_id'] for r in resolved)}）。\n")
            logger.info(f"[分镜管理] 会话 {session_id[:8]}... 分镜 {index} 自动匹配参考图: {status} {len(resolved)} 张")
            return {"status": status, "image_ids": [r["image_id"] for r in resolved]}

        except StoryboardError as e:
            # 用户主动取消（interrupt 置位导致 run 失败）→ 尊重取消意图，向上抛让 run 以失败终态结束
            if interrupt is not None and getattr(interrupt, "is_set", lambda: False)():
                raise
            logger.warning(f"[分镜管理] 会话 {session_id[:8]}... 分镜 {index} 参考图自动匹配失败: {e}")
            _emit(f"\n[参考图自动匹配失败: {e}｜已跳过，不影响已生成的提示词]\n")
            return {"status": "failed", "image_ids": []}
        except Exception:  # noqa: BLE001 — 兜底：匹配绝不阻断提示词结果
            logger.warning(f"[分镜管理] 会话 {session_id[:8]}... 分镜 {index} 参考图自动匹配异常", exc_info=True)
            _emit("\n[参考图自动匹配异常，已跳过，不影响已生成的提示词]\n")
            return {"status": "failed", "image_ids": []}

    def complete_segment(self, session_id: str, index: int, completed: bool = True) -> dict:
        """完成/取消完成单个分镜的配置（per-segment 确认；≥1 个完成即可进入视频生成）"""
        self.ensure_can_execute(session_id, "segment_management")
        with self._segment_lock(session_id):
            self._find_segment(self._get_outline_data(session_id), index)  # 存在性校验
            script_session_id, episode_id = self._storyboard_loc(session_id)
            seg = self.store.update_segment_fields(
                script_session_id, episode_id, session_id, index, {"configured": bool(completed)},
            )
        data = self._get_outline_data(session_id)
        segments = data.get("segments", [])
        configured_count = sum(1 for s in segments if s.get("configured"))
        logger.info(f"[分镜管理] 会话 {session_id[:8]}... 分镜 {index} 配置{'完成' if completed else '已取消'}（{configured_count}/{len(segments)}）")
        return {"segment": seg, "segment_count": len(segments), "configured_count": configured_count}


# ==================== 模块级辅助 ====================


def _ref_abs_path(image_path: str) -> str:
    """参考图路径渲染：本地相对路径展开为绝对路径（供 Agent Read 看图），URL 原样

    本地图先换 Agent 缩略图（大图 base64 回显会撑爆 SDK 流式 buffer 且 token 昂贵）。
    """
    if not image_path:
        return ""
    if image_path.startswith(("http://", "https://")):
        return f"（在线图：{image_path}）"
    return f"（本地图：{resolve_project_path(ensure_agent_thumbnail(image_path)).resolve()}）"


# 分镜标题行（`### `，与前端 /^###\s/ 一致；#### 更深层级不构成分镜）
_SEGMENT_HEADING = re.compile(r"^###\s")


def _norm_ws(text: str) -> str:
    """空白归一化（导图往返中多行/单行 outline 形态不一致，比较前先归一）"""
    return " ".join(text.split())
