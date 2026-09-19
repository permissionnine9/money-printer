"""同步 /video-prompt skill 文件到剧本工作区（渐进式披露）

Agent SDK 以隔离模式运行（setting_sources=[]），无法原生加载项目级 skill，
因此把 skill 文件复制进剧本工作区（99-references/video-prompt/），
agent prompt 中只留目录与必读指引，由 agent 用 Read 按需读取规范全文。
"""
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# backend/.claude/skills/video-prompt/
SKILL_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "video-prompt"

# references 按流水线顺序必读（场景扩写 → 电影级脚本 → 分镜设计）
_REFERENCE_ORDER = ["scene-expansion.md", "cinematic-script.md", "shot-and-sound.md"]

# 工作区内目标目录（相对 story 根）
SKILL_WORKSPACE_DIRNAME = "99-references/video-prompt"


def sync_video_prompt_skill(story_root: Path) -> Path:
    """把 SKILL.md + references/*.md 同步到 {story_root}/99-references/video-prompt/（幂等覆盖），返回目标目录"""
    skill_path = SKILL_DIR / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"video-prompt skill 不存在: {skill_path}")

    target_dir = story_root / SKILL_WORKSPACE_DIRNAME
    (target_dir / "references").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(skill_path, target_dir / "SKILL.md")
    for name in _REFERENCE_ORDER:
        ref_path = SKILL_DIR / "references" / name
        if not ref_path.exists():
            logger.warning(f"[video-prompt] 缺少参考文件: {ref_path}")
            continue
        shutil.copyfile(ref_path, target_dir / "references" / name)
    return target_dir
