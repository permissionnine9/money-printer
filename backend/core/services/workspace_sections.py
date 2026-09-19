"""工作区共享装配（收敛 agents 层多处重复的实现）

- workspace_section：Agent prompt 的「剧本工作区」段（目录路径 + MAP；可选 episode 裁剪到本集）
- workspace_envelope：步骤结果薄 envelope（内容产物落 workspace 文件，DB 行只留定位指针）
- episode_number：ep_01 → 1（解析失败返回极大值，保证排序时排在最后）
- load_story_logic / load_story_outline：故事逻辑与全剧大纲读取（工作区文件权威源）
- get_selected_episode：视频会话选集信息读取（视频工作流与分镜工作流共用）
"""
from backend.core.errors import WorkflowError
from backend.core.persistence.session_manager import SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore

# 解析失败的集号兜底值（排序时排在最后）
_EPISODE_NUM_FALLBACK = 10 ** 9


def episode_number(episode_id: str) -> int:
    """ep_01 → 1（解析失败返回极大值，保证排序时排在最后）"""
    try:
        return int(episode_id.split("_")[1])
    except (IndexError, ValueError, AttributeError):
        return _EPISODE_NUM_FALLBACK


def workspace_section(store: WorkspaceStore, script_session_id: str, episode_id: str | None = None) -> str:
    """Agent prompt 的「剧本工作区」段：目录路径 + MAP 摘要

    episode_id 非空时裁剪到本集视角（本集文件路径 + 跨集检索指引）；
    为空时给出全剧目录地图（大纲 / 分集 / 实体卡）。
    """
    entry = store.agent_entry(script_session_id)
    if not entry["available"]:
        return "（剧本工作区不可用）"
    lines = [
        f"剧本工作区根目录：{entry['story_root']}",
        f"目录地图（先 Read 了解全貌）：{entry['map_path']}",
    ]
    if episode_id:
        episode_path = store.episode_path(script_session_id, episode_id)
        if episode_path:
            lines.append(f"本集分集设计（必读）：{episode_path}")
        lines.extend([
            "全剧大纲：01-outline/outline.md（跨集伏笔与主线脉络）",
            "人物/场景/线索/伏笔实体卡：03-entities/（按 ID Grep 或按名字 Glob）",
            "前后集衔接：02-episodes/ 下相邻集文件的「结尾摘要」「因果链」小节",
        ])
    else:
        lines.extend([
            "全剧大纲：01-outline/outline.md",
            "已保存分集设计：02-episodes/（每集一文件，「结尾摘要」「因果链」小节供前后集衔接）",
            "已注册实体卡：03-entities/（人物/场景/线索/伏笔，frontmatter 含 entity_id）",
        ])
    return "\n".join(lines)


def workspace_envelope(store: WorkspaceStore, script_session_id: str, rel: str) -> dict:
    """步骤结果薄 envelope：rel 为相对 story 目录的路径（storyboard.md / 01-outline/outline.md）"""
    story = store.story_dir(script_session_id)
    base = f"workspace/{story.name}" if story else "workspace"
    return {"_artifact": "workspace", "path": f"{base}/{rel}"}


def load_story_logic(store: WorkspaceStore, sm: SessionManager, session_id: str) -> str:
    """故事逻辑读取（工作区文件优先，DB 老数据 fallback）"""
    logic = store.read_story_logic(session_id)
    if logic:
        return logic
    step = sm.get_step_result(session_id, "story_ideation")
    return step["result_data"].get("story_logic", "") if step else ""


def load_story_outline(store: WorkspaceStore, script_session_id: str) -> str:
    """读取剧本会话的全剧大纲（工作区文件）"""
    outline = store.read_outline(script_session_id)
    return outline.get("mindmap", "") if outline else ""


def get_selected_episode(sm: SessionManager, session_id: str) -> dict:
    """读取本会话绑定的剧本选集信息（script_session_id / episode_id / video_params）"""
    step = sm.get_step_result(session_id, "select_episode")
    if not step or not step.get("result_data"):
        raise WorkflowError("会话尚未完成第 1 步：从剧本选集（旧会话不兼容，请从「创作剧本」重新开始）")
    return step["result_data"]
