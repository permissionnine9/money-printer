"""剧本创作工作流（4 步）

1. story_ideation  故事构思：多轮对话盘问（Agent SDK resume 多轮），finalize 收敛故事逻辑
2. story_outline   故事大纲：单次 agent run 产出 markmap markdown
3. episode_design  分集设计：agent 通过进程内 MCP 工具注册全局实体并逐集落库（增量可见）
4. lookbook_images 定妆照：agent 出英文 prompt + 确定性生图（复用 ImageService）
"""
import asyncio
import json
import logging
import re
from typing import Optional

from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool

from backend.core.agent_sdk import READ_ONLY_TOOLS, AgentEvent, AgentRunOptions, run_agent, run_conversation
from backend.core.agents.system_prompts import LOOKBOOK_PROMPTS_SYSTEM, SCRIPT_OUTLINE_SYSTEM
from backend.core.agents.workflow_base import OnEvent, StepWorkflowBase
from backend.core.config import IMAGE_REQUEST_TIME_GAP
from backend.core.models import VideoParams
from backend.core.persistence import SessionManager
from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.workspace_store import WorkspaceStore
from backend.core.services.image_service import build_image_service_from_model_config
from backend.core.utils.json_parser import extract_json_array, extract_markdown, is_valid_mindmap

logger = logging.getLogger(__name__)

# 定妆照生图默认参数（锚点图，全剧统一）
LOOKBOOK_VIDEO_PARAMS = VideoParams(resolution="1080p", aspect_ratio="16:9")

# ending_summary 字数约束
ENDING_SUMMARY_MIN, ENDING_SUMMARY_MAX = 100, 300
CONFLICT_CHAIN_MAX = 2000
CAUSALITY_CHAIN_MAX = 2000
STORY_PROGRESS_MAX = 600

# get_context 已随文件化改造移除（Agent 直接 Read 工作区文件）

# 分集设计 max_turns 估算：每集 save+自纠 3 轮 + 固定开销 10 轮（规划/注册实体/汇报），设上下限
EPISODE_TURNS_BASE, EPISODE_TURNS_PER = 10, 3
EPISODE_TURNS_MIN, EPISODE_TURNS_MAX = 20, 200


class ScriptWorkflowError(Exception):
    """剧本工作流业务错误（返回给前端 detail；status_code 供全局异常 handler 使用）"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ScriptWorkflow(StepWorkflowBase):
    """剧本创作工作流"""

    Error = ScriptWorkflowError

    def __init__(
        self,
        session_manager: SessionManager,
        script_manager: Optional[ScriptManager] = None,
        store: Optional[WorkspaceStore] = None,
    ):
        super().__init__(session_manager)
        # scm 仅管 DB 侧任务表（定妆照/分集素材图状态机）；markdown 产物权威源为 store
        self.scm = script_manager or ScriptManager()
        if store is None:
            from backend.deps import get_workspace_store
            store = get_workspace_store()
        self.store = store

    def _envelope(self, session_id: str, rel: str) -> dict:
        """步骤结果薄 envelope：内容产物落 workspace 文件，DB 行只留定位指针"""
        story = self.store.story_dir(session_id)
        base = f"workspace/{story.name}" if story else "workspace"
        return {"_artifact": "workspace", "path": f"{base}/{rel}"}

    # ==================== 通用 ====================

    @staticmethod
    def _text_result(data) -> dict:
        """MCP 工具统一文本返回"""
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

    @staticmethod
    def _text_error(message: str) -> dict:
        """MCP 工具错误文本（返回给 agent 自纠，不抛异常）"""
        return {"content": [{"type": "text", "text": json.dumps({"ok": False, "error": message}, ensure_ascii=False)}]}

    # ==================== 第 1 步：故事构思（多轮对话） ====================

    async def ideation_message(
        self,
        session_id: str,
        user_message: str,
        on_event: OnEvent,
        interrupt: Optional[asyncio.Event] = None,
    ) -> dict:
        """处理一轮用户消息（resume agent 会话，消息副本供前端刷新还原）"""
        step = self.sm.get_step_result(session_id, "story_ideation")
        result_data = step["result_data"] if step else {}
        agent_session_id = result_data.get("agent_session_id", "")
        system_prompt = self.prompts.render("script_ideation", {})

        result = await run_conversation(
            message=user_message,
            system_prompt=system_prompt,
            agent_session_id=agent_session_id or None,
            on_event=on_event,
            interrupt=interrupt,
            max_turns=10,
        )
        if result.error:
            raise ScriptWorkflowError(f"构思对话失败: {result.error}")

        messages = list(result_data.get("messages", []))
        messages.append({"role": "user", "content": user_message})
        messages.append({"role": "assistant", "content": result.text})
        new_data = {
            **result_data,
            "agent_session_id": result.session_id or agent_session_id,
            "messages": messages,
        }
        # 对话轮次不推进步骤（finalize 才推进），首轮回调存中间状态
        if step:
            self.sm.update_step_result(session_id, "story_ideation", new_data)
        else:
            self.sm.save_step_result(session_id, "story_ideation", new_data, success=False)
        return {"assistant_message": result.text}

    async def ideation_finalize(
        self,
        session_id: str,
        on_event: OnEvent,
        interrupt: Optional[asyncio.Event] = None,
    ) -> dict:
        """收敛故事逻辑（同一 resume 会话），推进步骤"""
        step = self.sm.get_step_result(session_id, "story_ideation")
        result_data = step["result_data"] if step else {}
        agent_session_id = result_data.get("agent_session_id", "")
        if not agent_session_id:
            raise ScriptWorkflowError("请先进行至少一轮构思对话")

        system_prompt = self.prompts.render("script_ideation", {})
        finalize_prompt = self.prompts.render("script_ideation_finalize", {})
        result = await run_conversation(
            message=finalize_prompt,
            system_prompt=system_prompt,
            agent_session_id=agent_session_id,
            on_event=on_event,
            interrupt=interrupt,
            max_turns=10,
        )
        if result.error:
            raise ScriptWorkflowError(f"收敛故事逻辑失败: {result.error}")

        story_logic = result.text.strip()
        messages = list(result_data.get("messages", []))
        messages.append({"role": "assistant", "content": story_logic, "kind": "story_logic"})
        # story_logic 落 workspace 文件（权威源）；DB 只保留对话回放与 resume 句柄
        self.store.write_story_logic(session_id, story_logic)
        self.sm.save_step_result(session_id, "story_ideation", {
            **{k: v for k, v in result_data.items() if k != "story_logic"},
            "agent_session_id": result.session_id or agent_session_id,
            "messages": messages,
        }, success=True)
        return {"story_logic": story_logic}

    def update_story_logic(self, session_id: str, story_logic: str) -> dict:
        """人工编辑故事逻辑（不推进不重置，只写工作区文件）"""
        self.require_step_data(session_id, "story_ideation")
        self.store.write_story_logic(session_id, story_logic)
        return {"story_logic": story_logic}

    def get_ideation(self, session_id: str) -> dict:
        step = self.sm.get_step_result(session_id, "story_ideation")
        if not step:
            return {"messages": [], "story_logic": ""}
        return {
            **step["result_data"],
            "story_logic": self.store.read_story_logic(session_id)
            or step["result_data"].get("story_logic", ""),
        }

    # ==================== 第 2 步：故事大纲 ====================

    async def generate_outline(
        self,
        session_id: str,
        requirements: dict,
        on_event: OnEvent,
        interrupt: Optional[asyncio.Event] = None,
    ) -> dict:
        """生成故事大纲（单次 agent run）；重生成会级联清下游"""
        story_logic = self._load_story_logic(session_id)

        req_lines = []
        if requirements.get("episode_count"):
            req_lines.append(f"- 集数：{requirements['episode_count']} 集")
        if requirements.get("total_word_count"):
            req_lines.append(f"- 全剧总字数目标：约 {requirements['total_word_count']} 字")
        if requirements.get("scene_count"):
            req_lines.append(f"- 场景数量：{requirements.get('scene_count')} 个左右主要场景")
        extra = requirements.get("extra_prompt", "")
        if extra:
            req_lines.append(f"- 补充要求：{extra}")
        requirements_text = "## 生成要求\n" + "\n".join(req_lines) if req_lines else ""

        user_prompt = self.prompts.render("script_outline", {
            "requirements": requirements_text,
            "story_logic": story_logic,
            "extra_instruction": "",
        })

        result = await run_agent(
            AgentRunOptions(
                prompt=user_prompt,
                system_prompt=SCRIPT_OUTLINE_SYSTEM,
                max_turns=2,
                interrupt=interrupt,
            ),
            on_event,
        )
        if result.error:
            raise ScriptWorkflowError(f"大纲生成失败: {result.error}")

        mindmap = extract_markdown(result.text)
        if not is_valid_mindmap(mindmap):
            raise ScriptWorkflowError("大纲输出格式异常（未得到 markdown 层级结构），请重试")

        # 重生成 → 清下游（step_results + 工作区分集/实体 + DB 定妆照/素材图任务）
        self.sm.clear_steps_after(session_id, "story_outline")
        self.store.delete_story_content(session_id)
        self.scm.delete_script_data(session_id)
        # 大纲落工作区文件（story 目录随剧名正名），DB 行只留薄 envelope
        outline = self.store.write_outline(session_id, mindmap, requirements=requirements)
        self.sm.save_step_result(session_id, "story_outline",
                                 self._envelope(session_id, "01-outline/outline.md"), success=True)
        return {"mindmap": outline["mindmap"]}

    def update_outline(self, session_id: str, mindmap_markdown: str) -> dict:
        """人工编辑大纲（不推进不重置，写工作区文件）"""
        self.require_step_data(session_id, "story_outline")
        self.store.update_outline(session_id, mindmap_markdown)
        self.sm.update_step_result(session_id, "story_outline",
                                   self._envelope(session_id, "01-outline/outline.md"))
        warning = ""
        saved_episodes = self.store.list_episodes(session_id)
        if saved_episodes:
            parsed_count = _count_outline_episodes(mindmap_markdown)
            if parsed_count != len(saved_episodes):
                warning = (
                    f"新大纲解析为 {parsed_count} 集，与已保存的 {len(saved_episodes)} 集不一致，"
                    "请重新生成分集设计"
                )
        return {"mindmap": mindmap_markdown, "warning": warning}

    # ==================== 第 3 步：分集设计（agent + MCP 工具增量落库） ====================

    def _episode_number(self, episode_id: str) -> int:
        m = re.match(r"^ep_(\d+)$", episode_id)
        if not m:
            raise ScriptWorkflowError(f"episode_id 格式非法（应为 ep_01）: {episode_id}")
        return int(m.group(1))

    def _validate_episode(
        self, episode: dict, existing: list[dict], entities_by_id: dict,
        total_episodes: int = 0,
    ) -> None:
        """保存前强校验（失败抛 ScriptWorkflowError，由 handler 转错误文本让 agent 自纠）"""
        episode_id = episode.get("episode_id", "")
        num = self._episode_number(episode_id)

        # 集号连续：顺序保存时必须等于已有集数 + 1
        if existing and num != len(existing) + 1:
            raise ScriptWorkflowError(
                f"集号必须连续：当前应保存 ep_{len(existing) + 1:02d}，收到 {episode_id}"
            )
        if not existing and num != 1:
            raise ScriptWorkflowError("第一集必须从 ep_01 开始")

        character_ids = episode.get("character_ids") or []
        scene_ids = episode.get("scene_ids") or []
        if not character_ids:
            raise ScriptWorkflowError(f"{episode_id} 缺少出场人物（character_ids 至少 1 个）")
        if not scene_ids:
            raise ScriptWorkflowError(f"{episode_id} 缺少出场场景（scene_ids 至少 1 个）")

        plant_ep, payoff_ep = self._validate_episode_refs(episode, existing, entities_by_id)

        conflict = episode.get("conflict_chain", "")
        if len(conflict) > CONFLICT_CHAIN_MAX:
            raise ScriptWorkflowError(f"{episode_id} conflict_chain 超过 {CONFLICT_CHAIN_MAX} 字")
        causality = episode.get("causality_chain", "")
        if len(causality) > CAUSALITY_CHAIN_MAX:
            raise ScriptWorkflowError(f"{episode_id} causality_chain 超过 {CAUSALITY_CHAIN_MAX} 字")
        story_progress = episode.get("story_progress", "")
        if len(story_progress) > STORY_PROGRESS_MAX:
            raise ScriptWorkflowError(f"{episode_id} story_progress 超过 {STORY_PROGRESS_MAX} 字")
        ending = episode.get("ending_summary", "")
        if not (ENDING_SUMMARY_MIN <= len(ending) <= ENDING_SUMMARY_MAX):
            raise ScriptWorkflowError(
                f"{episode_id} ending_summary 须 {ENDING_SUMMARY_MIN}-{ENDING_SUMMARY_MAX} 字（当前 {len(ending)} 字）"
            )

        # 末集伏笔回收检查：已 plant 且从未 payoff 的伏笔必须补 payoff（open_ending 豁免）
        if total_episodes and num == total_episodes:
            unresolved = []
            for eid in sorted(set(plant_ep) - set(payoff_ep)):
                meta = (entities_by_id.get(eid) or {}).get("meta") or {}
                if not meta.get("open_ending"):
                    unresolved.append(eid)
            if unresolved:
                raise ScriptWorkflowError(
                    f"末集检查：以下伏笔已埋设但从未 payoff，请在本集补上 payoff"
                    f"（或在实体 meta 标记 open_ending=true 豁免）: {', '.join(unresolved)}"
                )

    def _validate_episode_refs(
        self, episode: dict, other_episodes: list[dict], entities_by_id: dict,
    ) -> tuple[dict, dict]:
        """引用校验核心（save_episode 与人工编辑 refs 共用）

        校验：引用存在性/类型匹配/action 合法 + 伏笔 payoff 晚于 plant + 线索 reveal 前置。
        other_episodes 为除当前集外的全部已保存集（合并当前集做全局计算）。
        返回 (plant_ep, payoff_ep) 供末集回收检查复用。
        """
        episode_id = episode.get("episode_id", "")
        num = self._episode_number(episode_id)

        for field, prefix in (
            ("character_ids", "chr"),
            ("scene_ids", "scn"),
        ):
            for eid in episode.get(field) or []:
                ent = entities_by_id.get(eid)
                if not ent or not eid.startswith(prefix):
                    raise ScriptWorkflowError(f"{episode_id} 引用了不存在或类型错误的实体: {eid}")
        for ref_field, prefix in (("clue_refs", "clu"), ("foreshadow_refs", "fs")):
            for ref in episode.get(ref_field) or []:
                eid = ref.get("entity_id", "") if isinstance(ref, dict) else ""
                if not eid or not entities_by_id.get(eid) or not eid.startswith(prefix):
                    raise ScriptWorkflowError(f"{episode_id} 引用了不存在或类型错误的实体: {eid}")
                action = ref.get("action", "")
                if action not in ("plant", "develop", "reveal", "payoff"):
                    raise ScriptWorkflowError(f"{episode_id} 的 {eid} action 非法: {action}")

        all_eps = other_episodes + [episode]
        plant_ep: dict[str, int] = {}
        payoff_ep: dict[str, int] = {}
        clue_prior_ep: dict[str, int] = {}
        for ep in all_eps:
            ep_num = self._episode_number(ep.get("episode_id", "ep_00"))
            for ref in ep.get("foreshadow_refs") or []:
                eid = ref.get("entity_id", "")
                if ref.get("action") == "plant":
                    plant_ep[eid] = min(plant_ep.get(eid, 999), ep_num)
                elif ref.get("action") == "payoff":
                    payoff_ep[eid] = min(payoff_ep.get(eid, 999), ep_num)
            for ref in ep.get("clue_refs") or []:
                eid = ref.get("entity_id", "")
                if ref.get("action") in ("plant", "develop"):
                    clue_prior_ep[eid] = min(clue_prior_ep.get(eid, 999), ep_num)
        for eid, pay_num in payoff_ep.items():
            if eid not in plant_ep:
                raise ScriptWorkflowError(f"伏笔 {eid} 尚未 plant 就在集 ep_{pay_num:02d} payoff")
            if plant_ep[eid] >= pay_num:
                raise ScriptWorkflowError(
                    f"伏笔 {eid} 的 payoff 集号（ep_{pay_num:02d}）必须晚于 plant 集号（ep_{plant_ep[eid]:02d}）"
                )
        # 线索 reveal 前必须有更早集的 plant/develop
        for ref in episode.get("clue_refs") or []:
            if ref.get("action") == "reveal":
                eid = ref.get("entity_id", "")
                if clue_prior_ep.get(eid, 999) >= num:
                    raise ScriptWorkflowError(
                        f"线索 {eid} 在 {episode_id} reveal 之前，必须有更早集的 plant 或 develop"
                    )
        return plant_ep, payoff_ep

    def update_episode_fields(self, session_id: str, episode_id: str, fields: dict) -> dict:
        """人工编辑分集字段；refs 类字段走与 save_episode 相同的引用校验"""
        current = self.store.get_episode(session_id, episode_id)
        if not current:
            raise ScriptWorkflowError(f"分集不存在: {episode_id}", status_code=404)
        ref_fields = {"character_ids", "scene_ids", "clue_refs", "foreshadow_refs"}
        if ref_fields & fields.keys():
            merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
            entities_by_id = {e["entity_id"]: e for e in self.store.list_entities(session_id)}
            others = [e for e in self.store.list_episodes(session_id) if e["episode_id"] != episode_id]
            self._validate_episode_refs(merged, others, entities_by_id)
        updated = self.store.update_episode_fields(session_id, episode_id, fields)
        return updated or current

    def _build_design_mcp_server(self, session_id: str, single_episode_id: Optional[str] = None):
        """构建分集设计工具集（写侧 MCP；读侧走工作区文件检索）；single_episode_id 限定只允许覆写该集（单集重设计）"""

        def _upsert(entity_type: str):
            @sdk_tool(
                f"upsert_{entity_type}",
                f"注册或更新{ {'character': '人物', 'scene': '场景', 'clue': '线索', 'foreshadow': '伏笔'}[entity_type] }，"
                "返回分配的 entity_id。同一实体只注册一次；更新时传 entity_id。",
                {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "名称（人物用姓名）"},
                        "description": {"type": "string", "description": "视觉描述（供生图，80字内）"},
                        "meta": {"type": "object", "description": "任意附加信息（性格/欲望/地点/埋设意图等）"},
                        "entity_id": {"type": "string", "description": "更新已有实体时传入；新增不传"},
                    },
                    "required": ["name"],
                },
            )
            async def upsert(args: dict) -> dict:
                try:
                    entity = self.store.upsert_entity(
                        session_id, entity_type,
                        args.get("name", ""),
                        args.get("description") or "",
                        args.get("meta") or {},
                        entity_id=args.get("entity_id") or None,
                    )
                    return self._text_result({"ok": True, "entity": entity})
                except ValueError as e:
                    return self._text_error(str(e))
            return upsert

        @sdk_tool(
            "save_episode",
            "保存一集分集设计（严格校验：引用存在/集号连续/伏笔 payoff 晚于 plant/每集至少1人物1场景）。校验失败会返回错误与原因，修正后重试。",
            {
                "type": "object",
                "properties": {
                    "episode_id": {"type": "string", "description": "ep_01、ep_02…"},
                    "title": {"type": "string"},
                    "logline": {"type": "string", "description": "一句话梗概（≤60字）"},
                    "conflict_chain": {"type": "string", "description": "本集矛盾链（欲望→阻力→选择→不可逆变化）"},
                    "causality_chain": {"type": "string", "description": "与前后集的因果衔接（≤2000字）"},
                    "ending_summary": {"type": "string", "description": "本集结尾摘要（100-300字，供下一集上下文）"},
                    "story_progress": {"type": "string", "description": "本集节点进展（200-500字，≤600字）：本集开局局面（承接上集）→ 本集推进 → 集尾各线状态（主线/线索/伏笔各一句）"},
                    "character_ids": {"type": "array", "items": {"type": "string"}},
                    "scene_ids": {"type": "array", "items": {"type": "string"}},
                    "clue_refs": {"type": "array", "items": {"type": "object"}, "description": '[{"entity_id": "clu_xxx", "action": "plant|develop|reveal"}]'},
                    "foreshadow_refs": {"type": "array", "items": {"type": "object"}, "description": '[{"entity_id": "fs_xxx", "action": "plant|develop|payoff"}]'},
                },
                "required": ["episode_id", "title", "logline", "conflict_chain", "causality_chain", "ending_summary", "character_ids", "scene_ids"],
            },
        )
        async def save_episode(args: dict) -> dict:
            episode = {
                "episode_id": args.get("episode_id", ""), "title": args.get("title", ""),
                "logline": args.get("logline", ""),
                "conflict_chain": args.get("conflict_chain", ""),
                "causality_chain": args.get("causality_chain", ""),
                "ending_summary": args.get("ending_summary", ""),
                "story_progress": args.get("story_progress", ""),
                "character_ids": args.get("character_ids") or [],
                "scene_ids": args.get("scene_ids") or [],
                "clue_refs": args.get("clue_refs") or [],
                "foreshadow_refs": args.get("foreshadow_refs") or [],
            }
            try:
                if single_episode_id and episode["episode_id"] != single_episode_id:
                    raise ScriptWorkflowError(f"本次为单集重设计，只允许保存 {single_episode_id}")
                existing = self.store.list_episodes(session_id)
                if single_episode_id:
                    existing = [e for e in existing if e["episode_id"] != single_episode_id]
                entities_by_id = {e["entity_id"]: e for e in self.store.list_entities(session_id)}
                outline = self.store.read_outline(session_id)
                total_episodes = (
                    _count_outline_episodes(outline.get("mindmap", "")) if outline else 0
                )
                self._validate_episode(episode, existing, entities_by_id, total_episodes=total_episodes)
                saved = self.store.upsert_episode(session_id, episode)
                return self._text_result({"ok": True, "episode": saved})
            except ScriptWorkflowError as e:
                return self._text_error(str(e))

        return create_sdk_mcp_server(
            name="script_design",
            version="1.0.0",
            tools=[_upsert("character"), _upsert("scene"), _upsert("clue"), _upsert("foreshadow"), save_episode],
        )

    def _workspace_section(self, session_id: str) -> str:
        """Agent prompt 的「剧本工作区」段（目录路径 + MAP）"""
        entry = self.store.agent_entry(session_id)
        if not entry["available"]:
            return "（剧本工作区不可用）"
        return "\n".join([
            f"剧本工作区根目录：{entry['story_root']}",
            f"目录地图（先 Read 了解全貌）：{entry['map_path']}",
            "全剧大纲：01-outline/outline.md",
            "已保存分集设计：02-episodes/（每集一文件，「结尾摘要」「因果链」小节供前后集衔接）",
            "已注册实体卡：03-entities/（人物/场景/线索/伏笔，frontmatter 含 entity_id）",
        ])

    async def generate_episodes(
        self,
        session_id: str,
        on_event: OnEvent,
        interrupt: Optional[asyncio.Event] = None,
        regenerate_episode_id: Optional[str] = None,
        extra_instruction: str = "",
    ) -> dict:
        """全量分集设计（或单集重设计）。regenerate_episode_id 非空时为单集覆写模式"""
        outline_data = self.store.read_outline(session_id)
        outline = (outline_data or {}).get("mindmap", "")
        if not outline:
            raise ScriptWorkflowError("大纲尚未生成，请先完成第 2 步", status_code=400)
        episode_count = _count_outline_episodes(outline)

        if regenerate_episode_id:
            if not self.store.get_episode(session_id, regenerate_episode_id):
                raise ScriptWorkflowError(f"分集不存在: {regenerate_episode_id}")
            task_prompt = self._build_single_episode_prompt(session_id, regenerate_episode_id, extra_instruction)
        else:
            # 全量生成前清空旧数据（step 下游 + 工作区实体/分集 + DB 定妆照/素材图任务）
            self.sm.clear_steps_after(session_id, "episode_design")
            self.store.delete_story_content(session_id)
            self.scm.delete_script_data(session_id)
            task_prompt = (
                "请根据大纲完成全部分集设计。\n\n"
                f"## 剧本工作区（你只可在该目录内使用 Read/Grep/Glob 自主检索，禁止越界）\n"
                f"{self._workspace_section(session_id)}\n\n"
                "## 任务步骤\n"
                "1. 先 Read 目录地图 MAP.md 与全剧大纲 01-outline/outline.md，规划实体与各集设计\n"
                f"2. 从 ep_01 到 ep_{episode_count:02d} 逐集调 save_episode 保存（共 {episode_count} 集）；"
                "写后几集前可 Read 已保存分集的「结尾摘要」「因果链」小节保证衔接"
                + (f"\n\n补充要求：{extra_instruction}" if extra_instruction else "")
            )

        system_prompt = self.prompts.render("episode_design", {})
        mcp_server = self._build_design_mcp_server(session_id, single_episode_id=regenerate_episode_id)
        # 轮次按集数估算（每集 3 轮 + 固定开销，见常量注释），上下限兜底
        turns = max(EPISODE_TURNS_MIN, min(EPISODE_TURNS_BASE + EPISODE_TURNS_PER * episode_count, EPISODE_TURNS_MAX))

        result = await run_agent(
            AgentRunOptions(
                prompt=task_prompt,
                system_prompt=system_prompt,
                mcp_servers={"script_design": mcp_server},
                # 读侧：剧本目录内自主检索；写侧：仅 save/upsert MCP 工具落盘
                tools=READ_ONLY_TOOLS,
                cwd=self.store.story_cwd(session_id),
                max_turns=turns,
                interrupt=interrupt,
            ),
            on_event,
        )
        if result.error:
            raise ScriptWorkflowError(f"分集设计失败: {result.error}")

        episodes = self.store.list_episodes(session_id)
        if not regenerate_episode_id and len(episodes) != episode_count:
            raise ScriptWorkflowError(
                f"分集不完整：大纲要求 {episode_count} 集，实际保存 {len(episodes)} 集，请重新生成"
            )

        # 全量生成成功 → 推进步骤（单集重设计不推进）
        if not regenerate_episode_id:
            self.sm.save_step_result(session_id, "episode_design", {
                "episode_count": len(episodes),
            }, success=True)
        return {
            "episode_count": len(episodes),
            "regenerated": regenerate_episode_id or "",
        }

    def _build_single_episode_prompt(self, session_id: str, episode_id: str, extra_instruction: str) -> str:
        """单集重设计上下文：工作区地图 + 实体清单 + 前一集结尾与因果 + 旧版设计（含引用） + 后一集梗概与因果"""
        episodes = self.store.list_episodes(session_id)
        entities = self.store.list_entities(session_id)
        num = self._episode_number(episode_id)
        prev = next((e for e in episodes if self._episode_number(e["episode_id"]) == num - 1), None)
        nxt = next((e for e in episodes if self._episode_number(e["episode_id"]) == num + 1), None)
        current = self.store.get_episode(session_id, episode_id)

        parts = [
            f"本次为「单集重设计」任务：只重新设计并保存 {episode_id}（工具只接受这一集）。",
            f"\n## 剧本工作区（你只可在该目录内使用 Read/Grep/Glob 自主检索，禁止越界）\n{self._workspace_section(session_id)}",
        ]
        if prev:
            parts.append(f"\n## 上一集（{prev['episode_id']}）结尾摘要（本集必须自然承接）\n{prev['ending_summary']}")
            parts.append(f"\n## 上一集（{prev['episode_id']}）因果衔接（其结尾如何引出本集）\n{prev['causality_chain']}")
        if current:
            parts.append(f"\n## 当前 {episode_id} 设计（将被覆写）\n标题：{current['title']}\n梗概：{current['logline']}")
            parts.append(
                "### 旧版实体引用（可调整，但删掉某伏笔/线索的 plant 会导致后集 payoff/reveal 校验失败）\n"
                + _format_episode_refs(current)
            )
        if nxt:
            parts.append(f"\n## 下一集（{nxt['episode_id']}）梗概（本集结尾要为它铺垫，不可破坏其承接）\n{nxt['logline']}")
            parts.append(f"\n## 下一集（{nxt['episode_id']}）因果衔接（其开局承接描述，供参考）\n{nxt['causality_chain']}")
        parts.append("\n## 已注册实体（直接复用这些 entity_id，不要注册重复实体）")
        parts.append("\n".join(
            f"- {e['entity_id']} {e['name']}（{e['entity_type']}）" for e in entities
        ) or "（暂无）")
        parts.append(f"\n请调 save_episode 保存 {episode_id}（episode_id 不变）。")
        if extra_instruction:
            parts.append(f"\n补充要求：{extra_instruction}")
        return "\n".join(parts)

    # ==================== 第 4 步：定妆照 ====================

    async def generate_lookbook(
        self,
        session_id: str,
        entity_ids: list[str],
        style_prompt: str,
        model_config_id: Optional[str],
        on_event: OnEvent,
        interrupt: Optional[asyncio.Event] = None,
    ) -> dict:
        """定妆照生成：agent 单轮出英文 prompt → 确定性生图（间隔提交+并发轮询）"""
        self.require_step_data(session_id, "episode_design")
        if not entity_ids:
            raise ScriptWorkflowError("请至少勾选一个实体")

        # 校验勾选实体属于本会话
        owned = {e["entity_id"]: e for e in self.store.list_entities(session_id)}
        missing = [eid for eid in entity_ids if eid not in owned]
        if missing:
            raise ScriptWorkflowError(f"实体不存在或不属于本会话: {missing}")
        # 定妆照仅支持人物/场景，线索/伏笔无视觉形象
        invalid = [eid for eid in entity_ids if owned[eid]["entity_type"] not in ("character", "scene")]
        if invalid:
            raise ScriptWorkflowError(f"仅人物/场景可生成定妆照，线索/伏笔不支持: {invalid}")
        entities = [owned[eid] for eid in entity_ids]

        # 1. agent 单轮产出 prompt（story_logic 供 agent 判断本剧视觉风格）
        entities_text = "\n".join(
            f"- entity_id: {e['entity_id']} | 类型: {e['entity_type']} | 名称: {e['name']} | 设定: {e['description']}"
            for e in entities
        )
        story_logic = self._load_story_logic(session_id)[:1500]
        user_prompt = self.prompts.render("lookbook_prompts", {
            "story_logic": story_logic or "（无）",
            "style_prompt": style_prompt or "（用户未指定——请你根据剧本故事逻辑的题材与气质自行判断，并全剧统一）",
            "entities": entities_text,
        })
        on_event(AgentEvent(type="thinking", delta="正在生成定妆照 prompt..."))
        result = await run_agent(
            AgentRunOptions(
                prompt=user_prompt,
                system_prompt=LOOKBOOK_PROMPTS_SYSTEM,
                max_turns=2,
                interrupt=interrupt,
            ),
            on_event,
        )
        if result.error:
            raise ScriptWorkflowError(f"定妆照 prompt 生成失败: {result.error}")

        items = extract_json_array(result.text)
        if not items:
            raise ScriptWorkflowError("定妆照 prompt 输出解析失败，请重试")
        # 以勾选集为准；agent 缺漏的实体用设定兜底
        prompts_by_entity: dict[str, dict] = {}
        for item in items:
            eid = item.get("entity_id", "")
            if eid in owned:
                prompts_by_entity[eid] = {
                    "prompt": item.get("prompt", ""),
                    "description": item.get("description", ""),
                }
        for e in entities:
            if e["entity_id"] not in prompts_by_entity:
                prompts_by_entity[e["entity_id"]] = {
                    "prompt": f"{e['name']}, {e['description']}, single subject, consistent character design, medium shot",
                    "description": f"{e['name']} 定妆照",
                }

        # 2. 确定性生图（沿用素材图间隔提交 + 并发轮询模式）
        image_service = build_image_service_from_model_config(model_config_id)
        rows = {}
        for e in entities:
            p = prompts_by_entity[e["entity_id"]]
            row = self.scm.insert_lookbook(session_id, e["entity_id"], p["prompt"], p["description"])
            rows[row["image_id"]] = row

        on_event(AgentEvent(type="thinking", delta=f"开始生成 {len(rows)} 张定妆照..."))
        submitted: list[tuple[str, str]] = []  # (image_id, request_id)
        for i, (image_id, row) in enumerate(rows.items()):
            if interrupt and interrupt.is_set():
                raise ScriptWorkflowError("已取消")
            if i > 0:
                await asyncio.sleep(IMAGE_REQUEST_TIME_GAP)
            try:
                submit = await image_service.submit_image_task(row["prompt"], LOOKBOOK_VIDEO_PARAMS, None)
                if submit.get("success"):
                    submitted.append((image_id, submit["request_id"]))
                    self.scm.update_lookbook(image_id, {"task_id": submit["request_id"], "task_status": "processing"})
                else:
                    self.scm.update_lookbook(image_id, {"task_status": "failed"})
                    logger.error(f"[定妆照] 提交失败 {row['entity_id']}: {submit.get('error')}")
            except Exception as e:  # noqa: BLE001
                self.scm.update_lookbook(image_id, {"task_status": "failed"})
                logger.error(f"[定妆照] 提交异常 {row['entity_id']}: {e}")

        async def poll_one(image_id: str, request_id: str) -> None:
            poll = await image_service.poll_i2i_task(request_id, timeout=180, poll_interval=5)
            if poll.get("success"):
                self.scm.update_lookbook(image_id, {"image_path": poll.get("image_url", ""), "task_status": "completed"})
                lookbook = self.scm.get_lookbook(image_id)
                self.store.set_entity_lookbook(
                    session_id, lookbook["entity_id"], image_id, poll.get("image_url", ""),
                )
            else:
                self.scm.update_lookbook(image_id, {"task_status": "failed"})
                logger.error(f"[定妆照] 生成失败 {image_id}: {poll.get('error')}")

        if submitted:
            await asyncio.gather(*(poll_one(iid, rid) for iid, rid in submitted))

        final_rows = self.scm.list_lookbook(session_id)
        completed = sum(1 for r in final_rows if r["task_status"] == "completed")
        return {"total": len(rows), "completed": completed}

    async def regenerate_lookbook_image(
        self,
        session_id: str,
        image_id: str,
        prompt: Optional[str] = None,
        model_config_id: Optional[str] = None,
    ) -> dict:
        """单张定妆照重生成（可选改 prompt）"""
        row = self.scm.get_lookbook(image_id)
        if not row or row["script_session_id"] != session_id:
            raise ScriptWorkflowError(f"定妆照不存在: {image_id}")
        image_service = build_image_service_from_model_config(model_config_id)
        self.scm.update_lookbook(image_id, {"task_status": "processing", **({"prompt": prompt} if prompt else {})})
        submit = await image_service.submit_image_task(prompt or row["prompt"], LOOKBOOK_VIDEO_PARAMS, None)
        if not submit.get("success"):
            self.scm.update_lookbook(image_id, {"task_status": "failed"})
            raise ScriptWorkflowError(f"提交失败: {submit.get('error')}")
        self.scm.update_lookbook(image_id, {"task_id": submit["request_id"]})
        poll = await image_service.poll_i2i_task(submit["request_id"], timeout=180, poll_interval=5)
        if not poll.get("success"):
            self.scm.update_lookbook(image_id, {"task_status": "failed"})
            raise ScriptWorkflowError(f"生成失败: {poll.get('error')}")
        self.scm.update_lookbook(image_id, {"image_path": poll["image_url"], "task_status": "completed"})
        self.store.set_entity_lookbook(session_id, row["entity_id"], image_id, poll["image_url"])
        return self.scm.get_lookbook(image_id)

    def _load_story_logic(self, session_id: str) -> str:
        """故事逻辑读取（工作区文件优先，DB 老数据 fallback）"""
        logic = self.store.read_story_logic(session_id)
        if logic:
            return logic
        step = self.sm.get_step_result(session_id, "story_ideation")
        return step["result_data"].get("story_logic", "") if step else ""

    def complete_lookbook(self, session_id: str) -> dict:
        """手动确认完成第 4 步（按需勾选无自然终点）"""
        self.ensure_can_execute(session_id, "lookbook_images")
        self.sm.save_step_result(session_id, "lookbook_images", {
            "completed": True,
        }, success=True)
        return {"completed": True}


# ==================== 模块级辅助 ====================


def _count_outline_episodes(outline: str) -> int:
    """从大纲 markdown 数集分支数量（第 N 集（二级/三级标题）/ EP N / 集数兜底）"""
    matches = re.findall(
        r"^#{2,3}\s*(?:第\s*(\d+)\s*集|EP\s*(\d+))", outline, re.MULTILINE | re.IGNORECASE,
    )
    if matches:
        return len(matches)
    # 兜底：取所有 ## 分支数
    return max(len(re.findall(r"^##\s+", outline, re.MULTILINE)), 1)


def _format_episode_refs(episode: dict) -> str:
    """把单集实体引用渲染为可读文本（人物/场景/线索/伏笔，含动作）"""
    lines = [
        "出场人物：" + ("、".join(episode.get("character_ids") or []) or "无"),
        "出场场景：" + ("、".join(episode.get("scene_ids") or []) or "无"),
    ]
    for field, label in (("clue_refs", "线索"), ("foreshadow_refs", "伏笔")):
        refs = episode.get(field) or []
        lines.append(f"{label}：" + ("、".join(
            f"{r.get('entity_id', '')}（{r.get('action', '')}）" for r in refs
        ) or "无"))
    return "\n".join(lines)
