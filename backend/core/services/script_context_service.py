"""剧本上下文装配器：为视频工作流（分镜脚本/参考图/帧 prompt）构建剧本侧上下文

数据源：工作区文件（WorkspaceStore，markdown 产物权威源）；
定妆照/素材图任务状态仍读 DB（scm）。
优先级：本集分集设计全文 > 上一集结尾摘要 > 人物/场景实体卡 > 伏笔关联集摘要 > 全局大纲摘要
各段有长度上限（超长截断），保证 prompt 总量可控。
"""
import logging

from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.workspace_store import WorkspaceStore
from backend.core.services.workspace_sections import episode_number, load_story_outline

logger = logging.getLogger(__name__)

OUTLINE_MAX_CHARS = 3500        # 全局大纲摘要上限
# 需容纳满额实体卡：前缀~17 + 描述~80 + 动机标签~11 + MOTIVATION_MAX_CHARS(150) ≈ 258
ENTITY_CARD_MAX_CHARS = 280     # 单个实体卡片上限
RELATED_EPISODE_MAX_CHARS = 300 # 单个关联集摘要上限
MOTIVATION_MAX_CHARS = 150       # 人物内在动机摘要上限
MOTIVATION_KEYS = ("性格", "欲望", "身份", "伤口")  # meta 中优先取的动机键


class ScriptContextService:
    """从剧本会话装配分镜上下文"""

    def __init__(self, script_manager: ScriptManager, store: WorkspaceStore):
        # scm：定妆照/素材图任务表（DB）；markdown 产物（分集/实体/大纲）读工作区文件
        self.scm = script_manager
        self.store = store

    def build_segment_script_context(self, script_session_id: str, episode_id: str) -> str:
        """装配「本集分镜脚本生成」的完整上下文"""
        episode = self.store.get_episode(script_session_id, episode_id)
        if not episode:
            raise ValueError(f"分集不存在: {episode_id}")

        entities = {e["entity_id"]: e for e in self.store.list_entities(script_session_id)}
        episodes = self.store.list_episodes(script_session_id)

        parts: list[str] = []

        # 1. 本集分集设计全文
        parts.append(f"## 本集分集设计（{episode_id}）")
        parts.append(f"标题：{episode['title']}\n梗概：{episode['logline']}")
        parts.append(f"矛盾链：\n{episode['conflict_chain']}")
        parts.append(f"因果链：\n{episode['causality_chain']}")
        parts.append(f"结尾摘要：\n{episode['ending_summary']}")
        # 本集节点进展（全文注入不截断）
        if episode.get("story_progress"):
            parts.append(f"本集节点进展：\n{episode['story_progress']}")

        # 2. 上一集结尾摘要（ep_01 无）
        prev = next(
            (e for e in episodes if episode_number(e["episode_id"]) == episode_number(episode_id) - 1),
            None,
        )
        if prev:
            parts.append(f"\n## 上一集（{prev['episode_id']}）结尾摘要（本集开场必须自然承接）")
            parts.append(_truncate(prev["ending_summary"], RELATED_EPISODE_MAX_CHARS * 2))

        # 3. 人物/场景实体卡（被本集引用的；视觉锚点 + 人物内在动机）
        cards = []
        for eid in episode["character_ids"] + episode["scene_ids"]:
            entity = entities.get(eid)
            if not entity:
                continue
            cards.append(_truncate(_entity_card(eid, entity), ENTITY_CARD_MAX_CHARS))
        if cards:
            parts.append("\n## 本集人物/场景设定（视觉一致性锚点 + 人物内在动机，供理解行动逻辑）")
            parts.extend(cards)

        # 4. 伏笔/线索关联集摘要（本集 refs 反查其它集）
        related_parts = self._build_foreshadow_related(episode, episodes, entities)
        if related_parts:
            parts.append("\n## 伏笔/线索关联（跨集埋设与回收）")
            parts.extend(related_parts)

        # 5. 全局大纲摘要（压缩兜底）
        outline = load_story_outline(self.store, script_session_id)
        if outline:
            parts.append("\n## 全剧大纲摘要")
            parts.append(_truncate(outline.replace("\n#", " "), OUTLINE_MAX_CHARS))

        return "\n".join(parts)

    def _build_foreshadow_related(
        self, episode: dict, episodes: list[dict], entities: dict,
    ) -> list[str]:
        """本集伏笔/线索引用反查其它集的梗概与结尾（同一集去重合并）"""
        foreshadow_ids = {r.get("entity_id") for r in episode.get("foreshadow_refs", [])}
        clue_ids = {r.get("entity_id") for r in episode.get("clue_refs", [])}
        ref_ids = foreshadow_ids | clue_ids
        if not ref_ids:
            return []
        now_refs = list(episode.get("foreshadow_refs", [])) + list(episode.get("clue_refs", []))
        parts = []
        current_num = episode_number(episode["episode_id"])
        for other in episodes:
            other_num = episode_number(other["episode_id"])
            if other_num == current_num:
                continue
            other_refs_list = list(other.get("foreshadow_refs", [])) + list(other.get("clue_refs", []))
            other_refs = {r.get("entity_id") for r in other_refs_list}
            shared = ref_ids & other_refs
            if not shared:
                continue
            names = "、".join(
                f"{eid}（{entities[eid]['name']}）" for eid in shared if eid in entities
            ) or "、".join(shared)
            action_now = {f"{r['entity_id']}:{r['action']}" for r in now_refs if r.get("entity_id") in shared}
            action_other = {f"{r['entity_id']}:{r['action']}" for r in other_refs_list if r.get("entity_id") in shared}
            summary = other["ending_summary"] if other_num < current_num else other["logline"]
            parts.append(_truncate(
                f"- {other['episode_id']}（{other['title']}）共享伏笔/线索 {names}："
                f"该集 {','.join(sorted(action_other))}，本集 {','.join(sorted(action_now))}。{summary}",
                RELATED_EPISODE_MAX_CHARS,
            ))
        return parts

def _entity_card(eid: str, entity: dict) -> str:
    """实体卡：视觉描述 + 人物内在动机摘要（供分镜理解行动逻辑）"""
    label = "人物" if eid.startswith("chr") else "场景"
    card = f"- {eid} {entity['name']}（{label}）：{entity['description']}"
    if label != "人物":
        return card
    meta = entity.get("meta") or {}
    bits = [f"{key}：{meta[key]}" for key in MOTIVATION_KEYS if meta.get(key)]
    if bits:
        card += f"（人物内在动机：{_truncate('；'.join(bits), MOTIVATION_MAX_CHARS)}）"
    return card


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…（截断）"
