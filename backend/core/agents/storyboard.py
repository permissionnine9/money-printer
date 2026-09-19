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
from datetime import datetime
from typing import Optional

from backend.core.agent_sdk import READ_ONLY_TOOLS, AgentEvent, AgentRunOptions, run_agent
from backend.core.agents.system_prompts import MATERIAL_GENERATE_SYSTEM, SEGMENT_PROMPT_SYSTEM, STORYBOARD_OUTLINE_SYSTEM
from backend.core.agents.workflow_base import OnEvent, StepWorkflowBase
from backend.core.models import StoryboardSegment, VideoParams
from backend.core.persistence import SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore
from backend.core.services.image_service import build_image_service_from_model_config
from backend.core.services.script_context_service import ScriptContextService
from backend.core.services.video_prompt_skill import load_video_prompt_skill
from backend.core.utils.image_store import archive_generated_image
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


class StoryboardError(Exception):
    """分镜工作流业务错误（返回给前端 detail；status_code 供全局异常 handler 使用）"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class StoryboardWorkflow(StepWorkflowBase):
    """分镜大纲生成与分镜管理"""

    Error = StoryboardError

    def __init__(self, session_manager: SessionManager, store: Optional[WorkspaceStore] = None):
        super().__init__(session_manager)
        self.script_context = ScriptContextService(store=store)
        if store is None:
            from backend.deps import get_workspace_store
            store = get_workspace_store()
        self.store = store
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
        return self.require_step_data(
            session_id, "select_episode",
            not_started_message="会话尚未完成第 1 步：从剧本选集",
        )

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
        script_session_id, episode_id = self._storyboard_loc(session_id)
        vs_dir = self.store.storyboard_dir(script_session_id, episode_id, session_id)
        return {"_artifact": "workspace", "path": (vs_dir / "storyboard.md").as_posix()}

    def _find_segment(self, data: dict, index: int) -> dict:
        seg = next((s for s in data.get("segments", []) if s.get("index") == index), None)
        if seg is None:
            raise StoryboardError(f"分镜 {index} 不存在")
        return seg

    def _load_story_outline(self, script_session_id: str) -> str:
        """读取剧本会话的全剧大纲（工作区文件）"""
        outline = self.store.read_outline(script_session_id)
        return outline.get("mindmap", "") if outline else ""

    def _story_cwd(self, script_session_id: str) -> Optional[str]:
        """Agent 工作目录（剧本 story 根，绝对路径）"""
        story = self.store.story_dir(script_session_id)
        return str(story.resolve()) if story else None

    # ==================== 第 2 步：分镜大纲 ====================

    def _workspace_section(self, script_session_id: str, episode_id: str, *, must_read_episode: bool = True) -> str:
        """Agent prompt 的「剧本工作区」段：目录路径 + MAP 摘要 + 本集文件路径（替代旧全文上下文）"""
        entry = self.store.agent_entry(script_session_id)
        if not entry["available"]:
            return "（剧本工作区不可用）"
        episode_path = self.store.episode_path(script_session_id, episode_id)
        lines = [
            f"剧本工作区根目录：{entry['story_root']}",
            f"目录地图（先 Read 了解全貌）：{entry['map_path']}",
            "全剧大纲：01-outline/outline.md（跨集伏笔与主线脉络）",
            "人物/场景/线索/伏笔实体卡：03-entities/（按 ID Grep 或按名字 Glob）",
            "前后集衔接：02-episodes/ 下相邻集文件的「结尾摘要」「因果链」小节",
        ]
        if episode_path:
            tag = "（必读）" if must_read_episode else ""
            lines.insert(2, f"本集分集设计{tag}：{episode_path}")
        return "\n".join(lines)

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

        user_prompt = self.prompts.render("storyboard_outline", {
            "video_params_context": video_params.to_prompt_context(),
            "workspace_section": self._workspace_section(script_session_id, selected["episode_id"]),
            "extra_instruction": f"\n\n## 用户额外要求\n{extra_prompt}\n请融入分镜切分。" if extra_prompt else "",
            "max_segment_duration": video_params.max_segment_duration,
        })

        result = await run_agent(
            AgentRunOptions(
                prompt=user_prompt,
                system_prompt=STORYBOARD_OUTLINE_SYSTEM,
                # 剧本目录内自主检索（Read/Grep/Glob），留足检索轮次后输出 JSON
                tools=READ_ONLY_TOOLS,
                cwd=self._story_cwd(script_session_id),
                max_turns=12,
                interrupt=interrupt,
            ),
            on_event,
        )
        if result.error:
            raise StoryboardError(f"分镜大纲生成失败: {result.error}")

        try:
            parsed = parse_json_response(result.text, default=None)
        except ValueError:  # default=None 时空文本/非 JSON 抛异常而非返回 None
            parsed = None
        if not isinstance(parsed, dict):
            raise StoryboardError("分镜大纲输出格式异常（未解析到 JSON），请重试")
        mindmap = (parsed.get("mindmap") or "").strip()
        if not is_valid_mindmap(mindmap):
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
                    segments.append({**old, "title": p["title"], "outline": p["outline"], "prompt": ""})
                else:  # 编辑新增的分镜：默认时长/overlap，提示词为空
                    segments.append(StoryboardSegment(
                        index=i, title=p["title"], outline=p["outline"],
                        duration=max_dur, overlap=1 if i > 0 else 0,
                    ).model_dump())
                segments[-1]["index"] = i  # title 匹配保留的旧分镜 index 已错位，统一重排

            if changed and self.sm.is_step_completed(session_id, "segment_management"):
                self.sm.clear_step_result(session_id, "segment_management")
                self.sm.clear_steps_after(session_id, "segment_management")
                self.sm.reset_current_step(session_id, "segment_management")

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
        """分镜变化统一收尾：单文件写回；提示词陈旧时清提示词并回退 segment_management 完成态"""
        if stale_prompt:
            seg_fields["prompt"] = ""
        script_session_id, episode_id = self._storyboard_loc(session_id)
        seg = self.store.update_segment_fields(
            script_session_id, episode_id, session_id, index, seg_fields,
        )
        if stale_prompt and self.sm.is_step_completed(session_id, "segment_management"):
            self.sm.clear_step_result(session_id, "segment_management")
            self.sm.clear_steps_after(session_id, "segment_management")
            self.sm.reset_current_step(session_id, "segment_management")
        return seg

    def update_segment_config(self, session_id: str, index: int, fields: dict) -> dict:
        """更新分镜配置（分镜形式 / overlap）

        mode 或 overlap 变化会清空该分镜已生成的提示词（提示词内嵌 overlap 语义）；
        若分镜管理已完成，则回退其完成状态（配置变化需重新确认）。
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

            seg = self._save_segment_change(
                session_id, index, seg_fields, stale_prompt=(mode is not None or overlap is not None),
            )

        return {"segment": seg}

    # ==================== 第 3 步：分镜参考素材图 ====================

    def _resolve_pool_image(self, script_session_id: str, image_id: str) -> dict:
        """解析素材池 ID → {image_id, image_path, description}；不存在/跨 story/未完成抛业务异常

        ID 规则：lookbook_lb_* 定妆照（script_context.fetch_lookbook_images 的形态）/ mat_* 分集素材图
        """
        scm = self.script_context.scm
        if image_id.startswith("lookbook_"):
            row = scm.get_lookbook(image_id[len("lookbook_"):])
        else:
            row = scm.get_episode_material(image_id)
        if not row or row.get("script_session_id") != script_session_id:
            raise StoryboardError(f"素材图不存在或不属于当前剧本: {image_id}")
        if not row.get("image_path"):
            raise StoryboardError(f"素材图尚未生成完成: {image_id}")
        return {
            "image_id": image_id,
            "image_path": row["image_path"],
            "description": row.get("description", ""),
        }

    def list_material_pool(self, session_id: str) -> dict:
        """选择弹窗素材池：定妆照（story 级）+ 本集素材 + 其他集素材（不跨 story）"""
        selected = self._get_selected(session_id)
        script_session_id = selected["script_session_id"]
        episode_id = selected["episode_id"]
        scm = self.script_context.scm

        groups = []
        lookbook = [
            {"image_id": m["image_id"], "image_path": m["image_path"], "description": m["description"]}
            for m in self.script_context.fetch_lookbook_images(script_session_id)
        ]
        if lookbook:
            groups.append({"key": "lookbook", "label": "定妆照", "materials": lookbook})

        episode_titles = {e["episode_id"]: (e.get("title") or "") for e in self.store.list_episodes(script_session_id)}
        by_episode: dict[str, list[dict]] = {}
        for row in scm.list_episode_materials(script_session_id, task_status="completed"):
            if not row.get("image_path"):
                continue
            by_episode.setdefault(row["episode_id"], []).append({
                "image_id": row["image_id"],
                "image_path": row["image_path"],
                "description": row.get("description", ""),
                "title": row.get("title", ""),
            })
        for eid in sorted(by_episode, key=lambda e: _episode_number(e)):
            label = f"本集素材（{eid}《{episode_titles.get(eid, '')}》）" if eid == episode_id \
                else f"{eid}《{episode_titles.get(eid, '')}》素材"
            groups.append({
                "key": "current" if eid == episode_id else f"episode_{eid}",
                "label": label,
                "episode_id": eid,
                "materials": by_episode[eid],
            })
        return {"groups": groups}

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
                pool = self._resolve_pool_image(selected["script_session_id"], image_id)
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

        mentioned = [self._resolve_pool_image(selected["script_session_id"], i) for i in mentioned_image_ids]
        uploads_root = resolve_project_path("static/uploads").resolve()
        for path in reference_paths:
            # resolve 后必须仍在 uploads 目录内（拒绝 ../.. 路径穿越）
            resolved = resolve_project_path(path).resolve()
            if uploads_root != resolved.parent and uploads_root not in resolved.parents:
                raise StoryboardError(f"非法的参考图路径: {path}")
            if not resolved.is_file():
                raise StoryboardError(f"参考图文件不存在: {path}")
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
        tpl = self.prompts.render("material_generate", {
            "workspace_section": self._workspace_section(script_session_id, episode_id),
            "segment_context": (
                f"标题：{seg.get('title', '')}\n大纲：{seg.get('outline', '')}\n建议时长：{seg.get('duration', '')} 秒"
            ),
            "mentioned_images": "\n".join(
                f"- {m['image_id']}《{m['description'] or '（无描述）'}》{_ref_abs_path(m['image_path'])}" for m in mentioned
            ) or "（无）",
            "uploaded_refs": "\n".join(f"- {p}" for p in reference_paths) or "（无）",
            "user_prompt": (user_prompt or "").strip() or "（无自定义要求，按分镜内容自由发挥）",
        })
        on_event(AgentEvent(type="thinking", delta="正在理解素材图需求..."))
        result = await run_agent(
            AgentRunOptions(
                prompt=tpl,
                system_prompt=MATERIAL_GENERATE_SYSTEM,
                tools=READ_ONLY_TOOLS,
                cwd=self._story_cwd(script_session_id),
                max_turns=8,
                interrupt=interrupt,
            ),
            on_event,
        )
        if result.error:
            raise StoryboardError(f"素材图需求理解失败: {result.error}")
        try:
            item = parse_json_response(result.text, default=None)
        except ValueError:  # default=None 时空文本/非 JSON 抛异常而非返回 None
            item = None
        if not isinstance(item, dict) or not (item.get("image_prompt") or "").strip():
            raise StoryboardError("素材图需求理解输出格式异常（未解析到 JSON），请重试")
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

        # 3. 生图（OpenAI 协议：提交即同步完成，poll 取回缓存结果）
        try:
            if interrupt is not None and getattr(interrupt, "is_set", lambda: False)():
                raise StoryboardError("已取消")
            image_service = build_image_service_from_model_config(model_config_id)
            video_params = VideoParams(**selected.get("video_params", {}))
            on_event(AgentEvent(type="thinking", delta="素材图生成中..."))
            submit = await image_service.submit_image_task(image_prompt, video_params, gen_refs or None)
            if not submit.get("success"):
                scm.update_episode_material(mat_id, {"task_status": "failed"})
                raise StoryboardError(f"素材图提交失败: {submit.get('error')}")
            scm.update_episode_material(mat_id, {"task_id": submit["request_id"], "task_status": "processing"})
            poll = await image_service.poll_i2i_task(submit["request_id"])
            if not poll.get("success"):
                scm.update_episode_material(mat_id, {"task_status": "failed"})
                raise StoryboardError(f"素材图生成失败: {poll.get('error')}")
        except StoryboardError:
            raise
        except Exception as e:  # noqa: BLE001
            scm.update_episode_material(mat_id, {"task_status": "failed"})
            raise StoryboardError(f"素材图生成异常: {e}")

        # 4. 归档图库 static/images/{story_name}/{episode_name}/
        story_name = self.store.story_title(script_session_id) or f"story_{script_session_id[:8]}"
        episode_name = selected.get("episode_title") or episode_id
        image_path = await archive_generated_image(poll["image_url"], story_name, episode_name, title, mat_id)

        # 5. 回写完成 + 自动关联当前分镜（锁内重读，防 lost update）
        scm.update_episode_material(mat_id, {
            "image_path": image_path,
            "task_status": "completed",
            "meta": {"origin": "ai", "segment_index": index, "user_prompt": (user_prompt or "").strip(),
                     "archived": not image_path.startswith("http")},
        })
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
            "story_outline": self._load_story_outline(selected["script_session_id"]),
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

        user_prompt = f"""## 提示词生成规范（必须完整遵循）
{load_video_prompt_skill()}

## 剧本工作区（你只可在该目录内使用 Read/Grep/Glob 自主检索，禁止越界）
{self._workspace_section(script_session_id, episode_id)}

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

        result = await run_agent(
            AgentRunOptions(
                prompt=user_prompt,
                system_prompt=system_prompt,
                # 剧本目录内自主检索，留足检索轮次
                tools=READ_ONLY_TOOLS,
                cwd=self._story_cwd(script_session_id),
                max_turns=12,
                interrupt=interrupt,
            ),
            on_event,
        )
        if result.error:
            raise StoryboardError(f"分镜提示词生成失败: {result.error}")

        prompt_text = result.text.strip()
        if not prompt_text:
            raise StoryboardError("分镜提示词生成为空，请重试")

        with self._segment_lock(session_id):
            script_session_id, episode_id = self._storyboard_loc(session_id)
            seg = self.store.update_segment_fields(
                script_session_id, episode_id, session_id, index, {"prompt": prompt_text},
            )
        logger.info(f"[分镜管理] 会话 {session_id[:8]}... 分镜 {index} 提示词已生成（{len(prompt_text)} 字）")
        return {"index": index, "prompt": prompt_text}

    def complete_segment_management(self, session_id: str) -> dict:
        """完成分镜配置（显式推进到第 4 步：视频生成）"""
        self.ensure_can_execute(session_id, "segment_management")

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


# ==================== 模块级辅助 ====================


def _ref_abs_path(image_path: str) -> str:
    """参考图路径渲染：本地相对路径展开为绝对路径（供 Agent Read 看图），URL 原样"""
    if not image_path:
        return ""
    if image_path.startswith(("http://", "https://")):
        return f"（在线图：{image_path}）"
    return f"（本地图：{resolve_project_path(image_path).resolve()}）"


def _episode_number(episode_id: str) -> int:
    """ep_01 → 1（解析失败返回 0，保证排序稳定）"""
    try:
        return int(episode_id.split("_")[1])
    except (IndexError, ValueError):
        return 0


# 分镜标题行（`### `，与前端 /^###\s/ 一致；#### 更深层级不构成分镜）
_SEGMENT_HEADING = re.compile(r"^###\s")


def _norm_ws(text: str) -> str:
    """空白归一化（导图往返中多行/单行 outline 形态不一致，比较前先归一）"""
    return " ".join(text.split())
