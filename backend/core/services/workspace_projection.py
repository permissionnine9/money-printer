"""工作区投影层：workspace 文件 + DB 薄 envelope → 旧 step_results JSON 形状

文件为权威源；DB 中的旧完整数据仅作 fallback（未导出过的历史会话兼容，cutover 后可移除）。
仅投影 markdown 类产物（story_logic / story_outline）；
story_ideation 的 messages/agent_session_id、select_episode、generate_videos、
lookbook 任务状态等非 markdown 数据始终以 DB 为准。
"""
from backend.core.persistence.session_manager import SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore


def script_step_results(sm: SessionManager, store: WorkspaceStore, session_id: str) -> dict:
    """剧本会话全步骤结果投影（形状与旧 sm.get_step_results_map 完全一致：步骤行含 result_data 键）"""
    results = {}
    for step_name, step in sm.get_step_results_map(session_id).items():
        rd = step["result_data"]
        if step_name == "story_ideation":
            logic = store.read_story_logic(session_id)
            step = {**step, "result_data": {
                **{k: v for k, v in rd.items() if k != "story_logic"},
                "story_logic": logic if logic else rd.get("story_logic", ""),
            }}
        elif step_name == "story_outline":
            outline = store.read_outline(session_id)
            if outline:
                # 文件为权威源；老数据（未导出）fallback 用 DB result_data
                step = {**step, "result_data": {
                    "mindmap": outline["mindmap"],
                    "edited": outline["edited"],
                    "requirements": outline.get("requirements") or {},
                }}
        results[step_name] = step
    return results


def script_title(sm: SessionManager, store: WorkspaceStore, session_id: str) -> str:
    """剧本展示名（文件 outline.title 优先；老数据 fallback 解析 DB mindmap）"""
    outline = store.read_outline(session_id)
    if outline:
        return outline.get("title", "")
    return sm.get_script_title(session_id)


def video_step_results(sm: SessionManager, store: WorkspaceStore, session_id: str) -> dict:
    """视频会话全步骤结果投影（行结构与 get_step_results_map 一致；storyboard_outline 内容来自分镜文件）"""
    results = {}
    for step_name, step in sm.get_step_results_map(session_id).items():
        rd = step["result_data"]
        if step_name == "storyboard_outline":
            selected = sm.get_step_result(session_id, "select_episode")
            if selected:
                sel = selected["result_data"]
                sb = store.read_storyboard(
                    sel.get("script_session_id", ""), sel.get("episode_id", ""), session_id,
                )
                if sb:
                    step = {**step, "result_data": {
                        **rd,
                        "mindmap": sb["mindmap"],
                        "edited": sb["edited"],
                        "segments": sb["segments"],
                        "segment_count": sb["segment_count"],
                    }}
        results[step_name] = step
    return results
