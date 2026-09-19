"""文件化创作工作区存储 —— 剧本/分镜中间产物的 markdown 权威数据源

目录树规范（一个剧本会话一棵 story 树；视频会话不建树，分镜挂在对应分集下）：

    workspace/
    └── {剧名}-{剧本会话id前8}/
        ├── MAP.md                          目录地图（自动渲染：结构/检索建议/Agent 边界）
        ├── 00-ideation/story-logic.md      故事逻辑（构思收敛产物）
        ├── 01-outline/outline.md           全剧大纲（mindmap markdown，根标题即剧名）
        ├── 02-episodes/ep_NN-标题.md       分集设计
        ├── 03-entities/{chr|scn|clu|fs}_NNN-名字.md   全局实体卡
        └── 04-storyboards/ep_NN/
            └── vs-{视频会话id前8}/         同分集多次创建视频会话 = 兄弟 vs 目录
                ├── storyboard.md           分镜大纲导图
                └── seg_NN-标题.md          分镜（大纲 + 提示词，配置在 frontmatter）

设计要点：
- 关联信息（人物/场景/伏笔引用、时长、overlap、参考图、edited 标志）全部存
  frontmatter 元数据；正文为 markdown 内容，人类可直接阅读编辑
- 返回 dict 的键与旧 SQLite row 完全一致（episodes/script_entities 表 → 文件投影零转换），
  API 层因此无需改动响应结构
- 原子写（tmp + os.replace）+ per-story 线程锁（防并发 lost update）
- story 目录定位：sessions.workspace_path 锚点优先，glob `*-{sid8}` 兜底
"""
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import frontmatter

from backend.core.config import WORKSPACE_DIR
from backend.core.utils.image_store import sanitize_name

logger = logging.getLogger(__name__)

# ID 白名单（API 路径参数直接拼 glob/文件路径，必须先过格式校验防元字符注入：
# 如 episode_id="*" 会令 glob("*-*.md") 误匹配并触发 _replace_doc_file 清空分集）
# 正则加固：\Z 绝对锚定（$ 放行尾换行）、[0-9] 显式 ASCII（\d 放行全角数字）
_EPISODE_ID_RE = re.compile(r"^ep_[0-9]{2,}\Z", re.ASCII)
_ENTITY_ID_RE = re.compile(r"^(chr|scn|clu|fs)_[0-9]{3,}\Z", re.ASCII)
# API/schema 共享的 pattern 字符串（pydantic/FastAPI 为 rust regex 引擎：
# 其 $ 即绝对末尾、[0-9] 为 ASCII——与上方 Python re 语义一致）
EPISODE_ID_PATTERN = r"^ep_[0-9]{2,}$"
ENTITY_ID_PATTERN = r"^(chr|scn|clu|fs)_[0-9]{3,}$"

# story 树子目录（数字前缀保证目录树浏览时的阅读顺序）
DIR_IDEATION = "00-ideation"
DIR_OUTLINE = "01-outline"
DIR_EPISODES = "02-episodes"
DIR_ENTITIES = "03-entities"
DIR_STORYBOARDS = "04-storyboards"
STORY_SUBDIRS = (DIR_IDEATION, DIR_OUTLINE, DIR_EPISODES, DIR_ENTITIES, DIR_STORYBOARDS)

# 实体 ID 分配全局唯一性锁：ID 跨 story 全局分配（glob MAX+1 非原子），
# per-story 锁保护不到跨会话并发，须用进程级锁
_ENTITY_ID_LOCK = threading.Lock()

ENTITY_ID_PREFIXES = {
    "character": "chr",
    "scene": "scn",
    "clue": "clu",
    "foreshadow": "fs",
}
ENTITY_TYPE_LABELS = {
    "character": "人物",
    "scene": "场景",
    "clue": "线索",
    "foreshadow": "伏笔",
}

# 分集正文的固定小节（标题 → episodes 表字段）
EPISODE_SECTIONS = (
    ("梗概", "logline"),
    ("矛盾链", "conflict_chain"),
    ("因果链", "causality_chain"),
    ("结尾摘要", "ending_summary"),
    ("节点进展", "story_progress"),
)

# 分镜正文的固定小节
SEGMENT_SECTIONS = (
    ("分镜大纲", "outline"),
    ("分镜提示词", "prompt"),
)

_SECTION_RE = re.compile(r"^##\s+(.*?)\s*$")
# 正文字段值中的行首 `## `（LLM 自由文本可能输出 markdown 标题）会与正文小节定界符冲突：
# 写入时在行首标题前加一个 `\`，读取时去掉一个——按已有反斜杠数量计数，
# 双射往返（原文 `\## x` ↔ 文件 `\\## x`），不会误解码原生转义形态
_ESCAPE_HEADING_RE = re.compile(r"^(\\*)(#{2,}\s)", re.MULTILINE)
_UNESCAPE_HEADING_RE = re.compile(r"^(\\+)(#{2,}\s)", re.MULTILINE)


def _escape_headings(text: str) -> str:
    return _ESCAPE_HEADING_RE.sub(lambda m: "\\" + m.group(1) + m.group(2), text or "")


def _unescape_headings(text: str) -> str:
    return _UNESCAPE_HEADING_RE.sub(lambda m: "\\" * (len(m.group(1)) - 1) + m.group(2), text or "")


def _require_episode_id(episode_id: str) -> str:
    if not _EPISODE_ID_RE.match(episode_id or ""):
        raise WorkspaceStoreError(f"非法的 episode_id（应为 ep_01 形式）: {episode_id!r}")
    return episode_id


def _require_entity_id(entity_id: str) -> str:
    if not _ENTITY_ID_RE.match(entity_id or ""):
        raise WorkspaceStoreError(f"非法的 entity_id（应为 chr_001/scn_001 形式）: {entity_id!r}")
    return entity_id


def _render_episode_content(episode: dict) -> str:
    """分集正文渲染：固定小节，字段值转义行首标题（防与定界符冲突）"""
    return "\n\n".join(
        f"## {label}\n{_escape_headings(episode.get(key) or '')}" for label, key in EPISODE_SECTIONS
    )


def _render_segment_content(seg: dict) -> str:
    """分镜正文渲染：大纲/提示词两节，值转义行首标题"""
    content = f"## 分镜大纲\n{_escape_headings(seg.get('outline', '') or '')}"
    if seg.get("prompt"):
        content += f"\n\n## 分镜提示词\n{_escape_headings(seg['prompt'])}"
    return content


class WorkspaceStoreError(ValueError):
    """工作区存储业务错误（含非法 ID 校验；继承 ValueError 以复用 API/MCP 层既有捕获）"""


def _now() -> str:
    return datetime.now().isoformat()


def _norm_yaml(value):
    """YAML 读回值归一化：datetime → isoformat 字符串（与 DB row 的 str 类型对齐）"""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _norm_yaml(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm_yaml(v) for v in value]
    return value


def _mindmap_title(mindmap: str) -> str:
    """取 mindmap 根标题（`# 剧名`），无则返回空串（与 SessionManager.get_script_title 一致）"""
    for line in (mindmap or "").splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _split_sections(content: str) -> dict[str, str]:
    """按 `## 标题` 行切分正文为 {标题: 文本}"""
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current: Optional[str] = None
    for line in content.split("\n"):
        m = _SECTION_RE.match(line)
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
            if current not in order:
                order.append(current)
        elif current is not None:
            sections[current].append(line)
    return {title: "\n".join(sections[title]).strip() for title in order}


def _doc_name(doc_id: str, name: str) -> str:
    """规范文件名：{id}-{净化后的标题}.md（id 前缀保证排序与 glob 精确匹配）"""
    return f"{doc_id}-{sanitize_name(name, max_len=30, fallback='untitled')}.md"


class WorkspaceStore:
    """文件化工作区存储（剧本会话一棵 story 树的读写入口）"""

    def __init__(self, workspace_dir: Path | str | None = None, session_manager=None):
        """
        Args:
            workspace_dir: 工作区根目录（默认项目根 workspace/；测试可注入临时目录）
            session_manager: 剧本会话 SessionManager（读锚点用；缺省延迟取 deps 单例）
        """
        self.root = Path(workspace_dir) if workspace_dir else WORKSPACE_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._sm = session_manager
        # per-story 可重入锁（公开方法可能嵌套调用：write_outline → rename_story）
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    # ==================== 锁与定位 ====================

    def _anchor_sm(self):
        if self._sm is None:
            # 延迟导入避免与 deps 单例循环（先例：script_context_service._load_outline）
            from backend.deps import get_script_session_manager
            self._sm = get_script_session_manager()
        return self._sm

    def _story_lock(self, script_session_id: str) -> threading.RLock:
        with self._locks_guard:
            lock = self._locks.get(script_session_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[script_session_id] = lock
            return lock

    def story_dir(self, script_session_id: str) -> Optional[Path]:
        """定位 story 目录（锚点优先，glob *-{sid8} 兜底）；不存在返回 None"""
        info = self._anchor_sm().get_session(script_session_id)
        anchor = (info or {}).get("workspace_path")
        if anchor:
            path = self.root / anchor
            if path.is_dir():
                return path
            logger.warning(f"[工作区] 锚点失效（{anchor}），回退目录名匹配")
        sid8 = script_session_id[:8]
        for path in sorted(self.root.glob(f"*-{sid8}")):
            if path.is_dir():
                return path
        return None

    def ensure_story(self, script_session_id: str, title: str = "") -> Path:
        """定位或创建 story 目录（title 为空用「未命名剧本」）"""
        story = self.story_dir(script_session_id)
        if story:
            return story
        with self._story_lock(script_session_id):
            story = self.story_dir(script_session_id)  # 双检（并发创建）
            if story:
                return story
            name = f"{sanitize_name(title or '未命名剧本', max_len=40)}-{script_session_id[:8]}"
            story = self.root / name
            story.mkdir(parents=True, exist_ok=True)
            for sub in STORY_SUBDIRS:
                (story / sub).mkdir(exist_ok=True)
            self._anchor_sm().set_workspace_path(script_session_id, name)
            self.refresh_map(story)
            logger.info(f"[工作区] 创建 story 目录 {name}")
            return story

    def rename_story(self, script_session_id: str, new_title: str) -> Path:
        """story 目录改名（剧名确定/变更时）；同步锚点与 MAP"""
        story = self.story_dir(script_session_id)
        if not story:
            raise WorkspaceStoreError(f"story 目录不存在: {script_session_id[:8]}...")
        new_name = f"{sanitize_name(new_title, max_len=40)}-{script_session_id[:8]}"
        if story.name == new_name:
            return story
        with self._story_lock(script_session_id):
            new_path = self.root / new_name
            if new_path.exists():
                raise WorkspaceStoreError(f"目标目录已存在: {new_name}")
            story.rename(new_path)
            self._anchor_sm().set_workspace_path(script_session_id, new_name)
            self.refresh_map(new_path)
            logger.info(f"[工作区] story 改名 {story.name} → {new_name}")
            return new_path

    def story_title(self, script_session_id: str) -> str:
        """story 展示名（目录名去掉 -sid8 后缀）"""
        story = self.story_dir(script_session_id)
        return story.name.rsplit("-", 1)[0] if story else ""

    def story_cwd(self, script_session_id: str) -> Optional[str]:
        """Agent 工作目录（剧本 story 根，绝对路径；供 run_agent 的 cwd）"""
        story = self.story_dir(script_session_id)
        return str(story.resolve()) if story else None

    # ==================== 通用文档读写 ====================

    def _read_doc(self, path: Path) -> Optional[tuple[dict, str]]:
        if not path.is_file():
            return None
        post = frontmatter.load(str(path))
        meta = {k: _norm_yaml(v) for k, v in post.metadata.items()}
        return meta, post.content.strip("\n")

    def _write_doc(self, path: Path, meta: dict, content: str) -> None:
        """frontmatter 文档原子写（建目录 + 静态原子写）"""
        path.parent.mkdir(parents=True, exist_ok=True)
        self._static_write(path, meta, content)

    @staticmethod
    def _replace_doc_file(directory: Path, doc_id: str, name: str, meta: dict, content: str) -> Path:
        """写入 {doc_id}-{name}.md 并清掉同 id 旧命名文件（标题/名字变更后重命名）"""
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / _doc_name(doc_id, name)
        for old in directory.glob(f"{doc_id}-*.md"):
            if old != target:
                old.unlink(missing_ok=True)
        WorkspaceStore._static_write(target, meta, content)
        return target

    @staticmethod
    def _static_write(path: Path, meta: dict, content: str) -> None:
        text = frontmatter.dumps(frontmatter.Post(content, **meta), sort_keys=False)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _refresh(self, story: Path) -> None:
        """写后惰性刷新 MAP（文件量小，全量重渲染开销可忽略）"""
        self.refresh_map(story)

    # ==================== 故事逻辑（第 1 步产物） ====================

    def write_story_logic(self, script_session_id: str, story_logic: str) -> None:
        story = self.ensure_story(script_session_id)
        with self._story_lock(script_session_id):
            self._write_doc(story / DIR_IDEATION / "story-logic.md", {"updated_at": _now()}, story_logic)

    def read_story_logic(self, script_session_id: str) -> str:
        doc = self._read_doc(self.story_dir(script_session_id) / DIR_IDEATION / "story-logic.md") \
            if self.story_dir(script_session_id) else None
        return doc[1].strip() if doc else ""

    # ==================== 全剧大纲（第 2 步产物） ====================

    def write_outline(
        self, script_session_id: str, mindmap: str,
        requirements: Optional[dict] = None, edited: bool = False,
    ) -> dict:
        """落盘全剧大纲；剧名取 mindmap 根标题，story 目录随剧名一次性正名"""
        title = _mindmap_title(mindmap)
        story = self.ensure_story(script_session_id, title)
        with self._story_lock(script_session_id):
            if title:
                wanted = f"{sanitize_name(title, max_len=40)}-{script_session_id[:8]}"
                if story.name != wanted:
                    story = self.rename_story(script_session_id, title)
            self._write_doc(story / DIR_OUTLINE / "outline.md", {
                "title": title,
                "edited": edited,
                "requirements": requirements or {},
                "created_at": _now(),
                "updated_at": _now(),
            }, mindmap)
            self._refresh(story)
        return self.read_outline(script_session_id) or {}

    def read_outline(self, script_session_id: str) -> Optional[dict]:
        """读取大纲（与旧 step_results.story_outline.result_data 形状一致）"""
        story = self.story_dir(script_session_id)
        if not story:
            return None
        doc = self._read_doc(story / DIR_OUTLINE / "outline.md")
        if not doc:
            return None
        meta, content = doc
        return {
            "mindmap": content,
            "title": meta.get("title", ""),
            "edited": bool(meta.get("edited", False)),
            "requirements": meta.get("requirements") or {},
        }

    def update_outline(self, script_session_id: str, mindmap: str) -> dict:
        """人工编辑大纲（edited=True；剧名变化时 story 随之正名）"""
        current = self.read_outline(script_session_id)
        if not current:
            raise WorkspaceStoreError("大纲尚未生成")
        title = _mindmap_title(mindmap) or current.get("title", "")
        story = self.story_dir(script_session_id)
        with self._story_lock(script_session_id):
            if title:
                wanted = f"{sanitize_name(title, max_len=40)}-{script_session_id[:8]}"
                if story and story.name != wanted:
                    story = self.rename_story(script_session_id, title)
            self._write_doc(story / DIR_OUTLINE / "outline.md", {
                "title": title,
                "edited": True,
                "requirements": current.get("requirements") or {},
                "created_at": _now(),
                "updated_at": _now(),
            }, mindmap)
            self._refresh(story)
        return self.read_outline(script_session_id) or {}

    # ==================== 实体注册表（全局实体卡） ====================

    def _scan_next_entity_id(self, entity_type: str) -> str:
        """无锁扫描实现（调用方须持有 _ENTITY_ID_LOCK）；跨全工作区 MAX+1，与旧 DB 全局唯一语义一致"""
        prefix = ENTITY_ID_PREFIXES[entity_type]
        max_num = 0
        for path in self.root.glob(f"*/{DIR_ENTITIES}/{prefix}_*.md"):
            m = re.match(rf"{prefix}_(\d+)", path.name)
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{prefix}_{max_num + 1:03d}"

    def _find_entity_file(self, script_session_id: str, entity_id: str) -> Optional[Path]:
        """在本 story 的实体目录内查找实体文件（限定范围：ID 全局唯一但写/删不得跨会话）"""
        _require_entity_id(entity_id)
        story = self.story_dir(script_session_id)
        if not story:
            return None
        for path in (story / DIR_ENTITIES).glob(f"{entity_id}-*.md"):
            return path
        return None

    def upsert_entity(
        self,
        script_session_id: str,
        entity_type: str,
        name: str,
        description: str = "",
        meta: Optional[dict] = None,
        entity_id: Optional[str] = None,
        create_if_missing: bool = False,
    ) -> dict:
        """新增或更新实体；entity_id 为空时分配新 ID（签名与 ScriptManager.upsert_entity 一致）

        entity_id 指定但文件不存在时默认报错（agent 自纠）；
        create_if_missing=True 允许按给定 ID 直接新建（DB→文件迁移路径）。
        """
        if entity_type not in ENTITY_ID_PREFIXES:
            raise ValueError(f"entity_type 仅支持 {tuple(ENTITY_ID_PREFIXES)}")
        if entity_id:
            _require_entity_id(entity_id)  # 校验先于 ensure_story：非法 ID 不留目录副作用
        now = _now()
        story = self.ensure_story(script_session_id)
        if entity_id:
            with self._story_lock(script_session_id):
                old_path = self._find_entity_file(script_session_id, entity_id)
                if not old_path:
                    if not create_if_missing:
                        raise ValueError(f"实体不存在: {entity_id}")
                    old_meta = {}
                else:
                    old_meta, _ = self._read_doc(old_path) or ({}, "")
                fm = {
                    "entity_id": entity_id,
                    "script_session_id": script_session_id,
                    "entity_type": entity_type,
                    "name": name,
                    "meta": meta or old_meta.get("meta") or {},
                    "lookbook_image_id": old_meta.get("lookbook_image_id", ""),
                    "lookbook_image_path": old_meta.get("lookbook_image_path", ""),
                    "created_at": old_meta.get("created_at", now),
                    "updated_at": now,
                }
                self._replace_doc_file(story / DIR_ENTITIES, entity_id, name, fm, description)
                self._refresh(story)
                return self.get_entity(script_session_id, entity_id) or {}

        # 新建：分配与落盘须在同一全局锁内原子完成（防跨会话并发撞号）
        with _ENTITY_ID_LOCK, self._story_lock(script_session_id):
            entity_id = self._scan_next_entity_id(entity_type)
            self._replace_doc_file(story / DIR_ENTITIES, entity_id, name, {
                "entity_id": entity_id,
                "script_session_id": script_session_id,
                "entity_type": entity_type,
                "name": name,
                "meta": meta or {},
                "lookbook_image_id": "",
                "lookbook_image_path": "",
                "created_at": now,
                "updated_at": now,
            }, description)
            self._refresh(story)
            return self.get_entity(script_session_id, entity_id) or {}

    @staticmethod
    def _entity_from_doc(path: Path, meta: dict, content: str) -> dict:
        """实体文件 → 旧 script_entities row 形状"""
        return {
            "entity_id": meta.get("entity_id", path.name.split("-", 1)[0]),
            "script_session_id": meta.get("script_session_id", ""),
            "entity_type": meta.get("entity_type", ""),
            "name": meta.get("name", ""),
            "description": content.strip(),
            "meta": meta.get("meta") or {},
            "lookbook_image_id": meta.get("lookbook_image_id", "") or "",
            "lookbook_image_path": meta.get("lookbook_image_path", "") or "",
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
        }

    def get_entity(self, script_session_id: str, entity_id: str) -> Optional[dict]:
        """读取实体（限定本 story；不存在或不属于该会话返回 None）"""
        path = self._find_entity_file(script_session_id, entity_id)
        if not path:
            return None
        doc = self._read_doc(path)
        return self._entity_from_doc(path, doc[0], doc[1]) if doc else None

    def list_entities(self, script_session_id: str, entity_type: Optional[str] = None) -> list[dict]:
        story = self.story_dir(script_session_id)
        if not story:
            return []
        pattern = f"{ENTITY_ID_PREFIXES[entity_type]}_*.md" if entity_type else "*.md"
        result = []
        for path in (story / DIR_ENTITIES).glob(pattern):
            doc = self._read_doc(path)
            if doc:
                result.append(self._entity_from_doc(path, doc[0], doc[1]))
        # 与旧 DB 排序一致：entity_type ASC, entity_id ASC
        result.sort(key=lambda e: (e["entity_type"], e["entity_id"]))
        return result

    def delete_entity(self, script_session_id: str, entity_id: str) -> bool:
        """删除实体（限定本 story；调用方需先校验分集反向引用）"""
        _require_entity_id(entity_id)
        story = self.story_dir(script_session_id)
        with self._story_lock(script_session_id):
            path = self._find_entity_file(script_session_id, entity_id)
            if not path:
                return False
            path.unlink(missing_ok=True)
            if story:
                self._refresh(story)
        return True

    def entity_references(self, script_session_id: str, entity_id: str) -> Optional[list[dict]]:
        """引用反查：该实体在全部分集中的引用方式（人物/场景 → 出场；线索/伏笔 → action 值）

        实体不存在或不属于该会话返回 None。
        """
        entity = self.get_entity(script_session_id, entity_id)
        if not entity or entity["script_session_id"] != script_session_id:
            return None
        entity_type = entity["entity_type"]
        episodes = []
        for ep in self.list_episodes(script_session_id):
            if entity_type == "character":
                actions = ["出场"] if entity_id in ep["character_ids"] else []
            elif entity_type == "scene":
                actions = ["出场"] if entity_id in ep["scene_ids"] else []
            else:
                refs = ep["clue_refs"] if entity_type == "clue" else ep["foreshadow_refs"]
                actions = [r.get("action", "") for r in refs if r.get("entity_id") == entity_id]
            if actions:
                episodes.append({"episode_id": ep["episode_id"], "title": ep["title"], "actions": actions})
        return episodes

    def delete_entity_unreferenced(self, script_session_id: str, entity_id: str) -> bool:
        """删除实体（同锁内校验无分集反向引用后删除，消除校验-删除 TOCTOU）

        被分集引用时 raise ValueError；不存在返回 False。
        """
        _require_entity_id(entity_id)
        story = self.story_dir(script_session_id)
        with self._story_lock(script_session_id):
            path = self._find_entity_file(script_session_id, entity_id)
            if not path:
                return False
            for episode in self.list_episodes(script_session_id):
                referenced = (
                    episode["character_ids"] + episode["scene_ids"]
                    + [r.get("entity_id") for r in episode["clue_refs"]]
                    + [r.get("entity_id") for r in episode["foreshadow_refs"]]
                )
                if entity_id in referenced:
                    raise ValueError(
                        f"实体 {entity_id} 被分集 {episode['episode_id']} 引用，先移除引用再删除"
                    )
            path.unlink(missing_ok=True)
            if story:
                self._refresh(story)
        return True

    def set_entity_lookbook(self, script_session_id: str, entity_id: str, image_id: str, image_path: str) -> bool:
        """回写实体的定妆照引用（限定本 story；定妆照任务本体仍在 DB，文件只存引用）"""
        _require_entity_id(entity_id)
        with self._story_lock(script_session_id):
            path = self._find_entity_file(script_session_id, entity_id)
            if not path:
                return False
            doc = self._read_doc(path)
            if not doc:
                return False
            meta, content = doc
            meta = {**meta, "lookbook_image_id": image_id, "lookbook_image_path": image_path, "updated_at": _now()}
            self._static_write(path, meta, content)
            return True

    # ==================== 分集设计 ====================

    def upsert_episode(self, script_session_id: str, episode: dict) -> dict:
        """插入或覆写一集（签名与 ScriptManager.upsert_episode 一致）"""
        episode_id = _require_episode_id(episode.get("episode_id", ""))
        now = _now()
        story = self.ensure_story(script_session_id)
        with self._story_lock(script_session_id):
            old = self.get_episode(script_session_id, episode_id)
            fm = {
                "episode_id": episode_id,
                "script_session_id": script_session_id,
                "title": episode.get("title", ""),
                "character_ids": episode.get("character_ids") or [],
                "scene_ids": episode.get("scene_ids") or [],
                "clue_refs": episode.get("clue_refs") or [],
                "foreshadow_refs": episode.get("foreshadow_refs") or [],
                "meta": episode.get("meta") or (old or {}).get("meta") or {},
                "edited": (old or {}).get("edited", False) if old else False,
                "created_at": (old or {}).get("created_at", now),
                "updated_at": now,
            }
            self._replace_doc_file(
                story / DIR_EPISODES, episode_id, fm["title"], fm, _render_episode_content(episode),
            )
            self._refresh(story)
            return self.get_episode(script_session_id, episode_id) or {}

    def update_episode_fields(self, script_session_id: str, episode_id: str, fields: dict) -> Optional[dict]:
        """人工编辑：部分字段更新（allowed 与旧 ScriptManager 一致；title 变更联动文件名）"""
        current = self.get_episode(script_session_id, episode_id)
        if not current:
            return None
        allowed = {
            "title", "logline", "conflict_chain", "causality_chain", "ending_summary", "story_progress",
            "character_ids", "scene_ids", "clue_refs", "foreshadow_refs",
        }
        merged = {**current, **{k: v for k, v in fields.items() if k in allowed}}
        story = self.story_dir(script_session_id)
        with self._story_lock(script_session_id):
            # 复用 upsert 的写文件逻辑，但保留 created_at/edited
            now = _now()
            fm = {
                "episode_id": episode_id,
                "script_session_id": script_session_id,
                "title": merged["title"],
                "character_ids": merged.get("character_ids") or [],
                "scene_ids": merged.get("scene_ids") or [],
                "clue_refs": merged.get("clue_refs") or [],
                "foreshadow_refs": merged.get("foreshadow_refs") or [],
                "meta": merged.get("meta") or {},
                "edited": True,
                "created_at": current.get("created_at", now),
                "updated_at": now,
            }
            self._replace_doc_file(
                story / DIR_EPISODES, episode_id, fm["title"], fm, _render_episode_content(merged),
            )
            self._refresh(story)
            return self.get_episode(script_session_id, episode_id)

    @staticmethod
    def _episode_from_doc(meta: dict, content: str) -> dict:
        """分集文件 → 旧 episodes row 形状（正文小节反转义还原字段值）"""
        sections = _split_sections(content)
        return {
            "episode_id": meta.get("episode_id", ""),
            "script_session_id": meta.get("script_session_id", ""),
            "title": meta.get("title", ""),
            "logline": _unescape_headings(sections.get("梗概", "")),
            "conflict_chain": _unescape_headings(sections.get("矛盾链", "")),
            "causality_chain": _unescape_headings(sections.get("因果链", "")),
            "ending_summary": _unescape_headings(sections.get("结尾摘要", "")),
            "story_progress": _unescape_headings(sections.get("节点进展", "")),
            "character_ids": meta.get("character_ids") or [],
            "scene_ids": meta.get("scene_ids") or [],
            "clue_refs": meta.get("clue_refs") or [],
            "foreshadow_refs": meta.get("foreshadow_refs") or [],
            "meta": meta.get("meta") or {},
            "edited": bool(meta.get("edited", False)),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
        }

    def _episode_files(self, script_session_id: str) -> list[Path]:
        story = self.story_dir(script_session_id)
        return sorted((story / DIR_EPISODES).glob("ep_*.md")) if story else []

    def get_episode(self, script_session_id: str, episode_id: str) -> Optional[dict]:
        _require_episode_id(episode_id)
        story = self.story_dir(script_session_id)
        if not story:
            return None
        for path in (story / DIR_EPISODES).glob(f"{episode_id}-*.md"):
            doc = self._read_doc(path)
            return self._episode_from_doc(doc[0], doc[1]) if doc else None
        return None

    def list_episodes(self, script_session_id: str) -> list[dict]:
        result = []
        for path in self._episode_files(script_session_id):
            doc = self._read_doc(path)
            if doc:
                result.append(self._episode_from_doc(doc[0], doc[1]))
        return result

    def delete_episode(self, script_session_id: str, episode_id: str) -> bool:
        _require_episode_id(episode_id)
        story = self.story_dir(script_session_id)
        if not story:
            return False
        deleted = False
        with self._story_lock(script_session_id):
            for path in (story / DIR_EPISODES).glob(f"{episode_id}-*.md"):
                path.unlink(missing_ok=True)
                deleted = True
            if deleted:
                self._refresh(story)
        return deleted

    def delete_last_episode(self, script_session_id: str, episode_id: str) -> bool:
        """删除分集（同锁内校验「只能删最后一集」，保持集号连续）

        非最后一集 raise ValueError；不存在返回 False。
        """
        _require_episode_id(episode_id)
        story = self.story_dir(script_session_id)
        if not story:
            return False
        with self._story_lock(script_session_id):
            episodes = self.list_episodes(script_session_id)
            if not episodes or episodes[-1]["episode_id"] != episode_id:
                raise ValueError("只能删除最后一集（保持集号连续）")
            deleted = False
            for path in (story / DIR_EPISODES).glob(f"{episode_id}-*.md"):
                path.unlink(missing_ok=True)
                deleted = True
            if deleted:
                self._refresh(story)
        return deleted

    def delete_story_content(self, script_session_id: str) -> dict:
        """大纲重生成的级联清理：清空分集与实体（02/03），返回清理计数

        （与旧 delete_script_data 对应；定妆照/素材图任务表仍在 DB，由调用方另行清理。
        04-storyboards 保留——视频会话数据不因剧本侧操作被删，与旧行为一致。）
        """
        story = self.story_dir(script_session_id)
        if not story:
            return {"episodes": 0, "entities": 0}
        with self._story_lock(script_session_id):
            def _count_and_clear(directory: Path) -> int:
                if not directory.is_dir():
                    return 0
                files = list(directory.glob("*.md"))
                for f in files:
                    f.unlink(missing_ok=True)
                return len(files)

            episodes = _count_and_clear(story / DIR_EPISODES)
            entities = _count_and_clear(story / DIR_ENTITIES)
            self._refresh(story)
        counts = {"episodes": episodes, "entities": entities}
        logger.info(f"[工作区] 清理下游数据 {script_session_id[:8]}...: {counts}")
        return counts

    def delete_story(self, script_session_id: str) -> bool:
        """删除整棵 story 树（删除剧本会话时调用）"""
        story = self.story_dir(script_session_id)
        if not story:
            return False
        with self._story_lock(script_session_id):
            import shutil
            shutil.rmtree(story)
        self._anchor_sm().set_workspace_path(script_session_id, None)
        logger.info(f"[工作区] 删除 story 目录 {story.name}")
        return True

    # ==================== 分镜（视频工作流第 2/3 步产物） ====================

    def storyboard_dir(self, script_session_id: str, episode_id: str, video_session_id: str) -> Path:
        """分镜目录（确定性拼出：04-storyboards/{ep}/vs-{视频会话id前8}）"""
        _require_episode_id(episode_id)
        story = self.ensure_story(script_session_id)
        return story / DIR_STORYBOARDS / episode_id / f"vs-{video_session_id[:8]}"

    def episode_path(self, script_session_id: str, episode_id: str) -> Optional[Path]:
        """分集文件绝对路径（供 Agent prompt 注入；不存在返回 None）"""
        _require_episode_id(episode_id)
        story = self.story_dir(script_session_id)
        if not story:
            return None
        for path in (story / DIR_EPISODES).glob(f"{episode_id}-*.md"):
            return path
        return None

    def segment_path(self, script_session_id: str, episode_id: str, video_session_id: str, index: int) -> Optional[Path]:
        """单分镜文件绝对路径（供 Agent prompt 注入）"""
        _require_episode_id(episode_id)
        story = self.story_dir(script_session_id)
        if not story:
            return None
        vs_dir = story / DIR_STORYBOARDS / episode_id / f"vs-{video_session_id[:8]}"
        return self._segment_file(vs_dir, index)

    def write_storyboard(
        self, script_session_id: str, episode_id: str, video_session_id: str,
        mindmap: str, segments: list[dict], edited: bool = False,
    ) -> dict:
        """生成分镜大纲：清空 vs 目录后整体重写（对应旧级联重置语义）"""
        _require_episode_id(episode_id)
        now = _now()
        with self._story_lock(script_session_id):
            vs_dir = self.storyboard_dir(script_session_id, episode_id, video_session_id)
            if vs_dir.exists():
                import shutil
                shutil.rmtree(vs_dir)
            vs_dir.mkdir(parents=True, exist_ok=True)
            self._static_write(vs_dir / "storyboard.md", {
                "episode_id": episode_id,
                "video_session_id": video_session_id,
                "edited": edited,
                "segment_count": len(segments),
                "created_at": now,
                "updated_at": now,
            }, mindmap)
            for seg in segments:
                self._write_segment_file(vs_dir, seg)
            self._refresh(self.story_dir(script_session_id))
        return self.read_storyboard(script_session_id, episode_id, video_session_id) or {}

    def _write_segment_file(self, vs_dir: Path, seg: dict) -> None:
        """单个分镜落盘（frontmatter 配置 + 正文大纲/提示词两节，值转义行首标题）"""
        fm = {
            "index": int(seg.get("index", 0)),
            "title": seg.get("title", ""),
            "mode": seg.get("mode", "all_reference"),
            "overlap": int(seg.get("overlap", 1)),
            "duration": int(seg.get("duration", 15)),
            "edited": bool(seg.get("edited", False)),
            "configured": bool(seg.get("configured", False)),
            "reference_images": seg.get("reference_images") or [],
            "updated_at": _now(),
        }
        self._replace_doc_file(vs_dir, f"seg_{fm['index']:02d}", fm["title"], fm, _render_segment_content(seg))

    @staticmethod
    def _segment_from_doc(path: Path, meta: dict, content: str) -> dict:
        sections = _split_sections(content)
        return {
            "index": int(meta.get("index", 0)),
            "title": meta.get("title", ""),
            "outline": _unescape_headings(sections.get("分镜大纲", "")),
            "mode": meta.get("mode", "all_reference"),
            "overlap": int(meta.get("overlap", 1)),
            "duration": int(meta.get("duration", 15)),
            "edited": bool(meta.get("edited", False)),
            "configured": bool(meta.get("configured", False)),
            "prompt": _unescape_headings(sections.get("分镜提示词", "")),
            "reference_images": meta.get("reference_images") or [],
            "updated_at": meta.get("updated_at", ""),
        }

    def _segment_file(self, vs_dir: Path, index: int) -> Optional[Path]:
        for path in vs_dir.glob(f"seg_{index:02d}-*.md"):
            return path
        return None

    def read_storyboard(self, script_session_id: str, episode_id: str, video_session_id: str) -> Optional[dict]:
        """读取分镜（与旧 step_results.storyboard_outline.result_data 形状一致）"""
        _require_episode_id(episode_id)
        story = self.story_dir(script_session_id)
        if not story:
            return None
        vs_dir = story / DIR_STORYBOARDS / episode_id / f"vs-{video_session_id[:8]}"
        doc = self._read_doc(vs_dir / "storyboard.md")
        if not doc:
            return None
        meta, content = doc
        segments = []
        for path in vs_dir.glob("seg_*.md"):
            seg_doc = self._read_doc(path)
            if seg_doc:
                segments.append(self._segment_from_doc(path, seg_doc[0], seg_doc[1]))
        segments.sort(key=lambda s: s["index"])
        return {
            "mindmap": content,
            "edited": bool(meta.get("edited", False)),
            "segments": segments,
            "segment_count": len(segments),
        }

    def replace_storyboard(
        self, script_session_id: str, episode_id: str, video_session_id: str,
        *, mindmap: Optional[str] = None, segments: Optional[list[dict]] = None, edited: Optional[bool] = None,
    ) -> dict:
        """整体替换 mindmap 和/或 segments（人工编辑导图 reconcile 后调用；不改 created_at）"""
        _require_episode_id(episode_id)
        with self._story_lock(script_session_id):
            current = self.read_storyboard(script_session_id, episode_id, video_session_id)
            if not current:
                raise WorkspaceStoreError("分镜尚未生成")
            vs_dir = self.storyboard_dir(script_session_id, episode_id, video_session_id)
            if segments is not None:
                # 分镜可能增删/改名：清旧文件后重写（seg_NN 前缀由 index 决定）
                for path in vs_dir.glob("seg_*.md"):
                    path.unlink(missing_ok=True)
                for seg in segments:
                    self._write_segment_file(vs_dir, seg)
            if mindmap is not None or edited is not None:
                sb_doc = self._read_doc(vs_dir / "storyboard.md")
                if sb_doc:
                    meta, _ = sb_doc
                    meta = {
                        **meta,
                        "edited": edited if edited is not None else bool(meta.get("edited", False)),
                        "segment_count": len(segments) if segments is not None else meta.get("segment_count", 0),
                        "updated_at": _now(),
                    }
                    self._static_write(vs_dir / "storyboard.md", meta, mindmap if mindmap is not None else sb_doc[1])
            self._refresh(self.story_dir(script_session_id))
        return self.read_storyboard(script_session_id, episode_id, video_session_id) or {}

    def update_segment_fields(
        self, script_session_id: str, episode_id: str, video_session_id: str, index: int, fields: dict,
    ) -> Optional[dict]:
        """单分镜部分更新（mode/overlap/duration/reference_images/outline/title/prompt；整文件重写）"""
        _require_episode_id(episode_id)
        with self._story_lock(script_session_id):
            story = self.story_dir(script_session_id)
            vs_dir = story / DIR_STORYBOARDS / episode_id / f"vs-{video_session_id[:8]}"
            path = self._segment_file(vs_dir, index)
            if not path:
                return None
            doc = self._read_doc(path)
            if not doc:
                return None
            meta, content = doc
            seg = self._segment_from_doc(path, meta, content)
            seg.update({k: v for k, v in fields.items() if k in (
                "title", "outline", "mode", "overlap", "duration", "prompt", "reference_images", "configured",
            )})
            self._replace_doc_file(vs_dir, f"seg_{index:02d}", seg["title"], {
                **{k: v for k, v in seg.items() if k not in ("outline", "prompt")},
                "edited": True,
                "updated_at": _now(),
            }, _render_segment_content(seg))
            self._refresh(story)
            return self.read_segment(script_session_id, episode_id, video_session_id, index)

    def read_segment(self, script_session_id: str, episode_id: str, video_session_id: str, index: int) -> Optional[dict]:
        _require_episode_id(episode_id)
        story = self.story_dir(script_session_id)
        if not story:
            return None
        vs_dir = story / DIR_STORYBOARDS / episode_id / f"vs-{video_session_id[:8]}"
        path = self._segment_file(vs_dir, index)
        if not path:
            return None
        doc = self._read_doc(path)
        return self._segment_from_doc(path, doc[0], doc[1]) if doc else None

    # ==================== MAP.md 渲染 ====================

    def refresh_map(self, story: Path) -> None:
        """按 story 目录当前内容重渲染 MAP.md（目录地图 + 检索建议 + Agent 边界）"""
        story.mkdir(parents=True, exist_ok=True)
        title = story.name.rsplit("-", 1)[0]
        lines: list[str] = [
            f"# 工作区地图：{title}",
            "",
            "> 本文件由系统自动维护，是本剧本全部创作产物的目录地图与检索指引。",
            "",
            "## 目录结构",
            "",
            "- `MAP.md` — 本地图",
            "- `00-ideation/story-logic.md` — 故事逻辑（构思收敛的故事设定全集）",
            "- `01-outline/outline.md` — 全剧大纲（markdown 思维导图，根标题即剧名）",
        ]

        episodes = sorted((story / DIR_EPISODES).glob("ep_*.md"))
        if episodes:
            lines.append(f"- `02-episodes/` — 分集设计（{len(episodes)} 集）：")
            lines.extend(f"  - `{p.name}`" for p in episodes)
        else:
            lines.append("- `02-episodes/` — 分集设计（暂无）")

        entities = sorted((story / DIR_ENTITIES).glob("*.md"))
        if entities:
            by_type: dict[str, list[str]] = {}
            for p in entities:
                etype = next(
                    (label for prefix, label in (
                        ("chr_", "人物"), ("scn_", "场景"), ("clu_", "线索"), ("fs_", "伏笔"),
                    ) if p.name.startswith(prefix)),
                    "其他",
                )
                by_type.setdefault(etype, []).append(p.name)
            lines.append(f"- `03-entities/` — 实体卡（{len(entities)} 个）：")
            for label in ("人物", "场景", "线索", "伏笔"):
                for name in by_type.get(label, []):
                    lines.append(f"  - `{name}`（{label}）")
        else:
            lines.append("- `03-entities/` — 实体卡（暂无）")

        vs_dirs = sorted((story / DIR_STORYBOARDS).glob("ep_*/vs-*"))
        if vs_dirs:
            lines.append("- `04-storyboards/` — 视频工作流分镜（按分集/视频会话组织）：")
            lines.extend(f"  - `{p.parent.name}/{p.name}/`（storyboard.md 导图 + seg_NN 分镜文件）" for p in vs_dirs)
        else:
            lines.append("- `04-storyboards/` — 视频工作流分镜（暂无）")

        foreshadow = next((p.name.split("-", 1)[0] for p in entities if p.name.startswith("fs_")), "")
        lines.extend([
            "",
            "## 检索建议",
            "",
            "- 全剧脉络与跨集伏笔：Read `01-outline/outline.md`",
            "- 查人物/场景设定：Glob `03-entities/*.md`，或按名字 Grep",
            f"- 追某个伏笔的跨集动作（如 `{foreshadow or 'fs_001'}`）：Grep 该 ID，"
            "命中各分集 frontmatter 的 foreshadow_refs 即埋设/回收位置",
            "- 读某集结尾承接：Read 对应 `02-episodes/ep_NN-*.md` 的「结尾摘要」小节",
            "- 分镜大纲与单镜提示词：Read `04-storyboards/{集}/vs-{会话}/` 下的 storyboard.md 与 seg_NN 文件",
            "",
            "## 边界规则（Agent 必须遵守）",
            "",
            f"- 只能在本目录（`{story.name}/`）内使用 Read/Grep/Glob，禁止读取工作区之外的任何路径",
            "- 所有产物由系统统一写入；你只具备读权限，生成结果按任务要求返回",
        ])
        self._static_write(story / "MAP.md", {"updated_at": _now()}, "\n".join(lines) + "\n")

    # ==================== 工作区入口（供 Agent prompt 使用） ====================

    def agent_entry(self, script_session_id: str) -> dict:
        """Agent 工作区入口信息（绝对路径 + MAP 摘要，供 prompt 注入）"""
        story = self.story_dir(script_session_id)
        if not story:
            return {"available": False}
        map_path = story / "MAP.md"
        map_text = map_path.read_text(encoding="utf-8") if map_path.is_file() else ""
        # 摘要取「目录结构」一节（检索建议与边界规则由调用方附加，避免重复）
        summary = map_text.split("## 检索建议")[0].strip() if map_text else ""
        return {
            "available": True,
            "story_root": str(story.resolve()),
            "map_path": str(map_path.resolve()),
            "map_summary": summary,
        }
