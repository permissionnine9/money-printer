"""加载 /video-prompt skill 全文（注入 agent prompt）

Agent SDK 以隔离模式运行（setting_sources=[]），无法原生加载项目级 skill，
因此运行时读取 skill 文件全文拼进提示词，让 agent 遵循该规范生成分镜提示词。
"""
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# backend/.claude/skills/video-prompt/
SKILL_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "video-prompt"

# references 按流水线顺序拼接（场景扩写 → 电影级脚本 → 分镜设计）
_REFERENCE_ORDER = ["scene-expansion.md", "cinematic-script.md", "shot-and-sound.md"]


@lru_cache(maxsize=1)
def load_video_prompt_skill() -> str:
    """读取 SKILL.md + references/*.md 全文并拼接为一段提示词规范文本"""
    skill_path = SKILL_DIR / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"video-prompt skill 不存在: {skill_path}")

    parts: list[str] = [skill_path.read_text(encoding="utf-8")]

    for name in _REFERENCE_ORDER:
        ref_path = SKILL_DIR / "references" / name
        if not ref_path.exists():
            logger.warning(f"[video-prompt] 缺少参考文件: {ref_path}")
            continue
        parts.append(f"\n\n---\n\n# 参考文件：references/{name}\n\n" + ref_path.read_text(encoding="utf-8"))

    return "".join(parts)
