"""步骤结果装配：DB 薄 envelope 行 + workspace 文件 → step_results 响应形状

markdown 类产物（story_logic / story_outline / storyboard）以 workspace 文件为
权威源，直接读 store 返回文件内容形状；select_episode / generate_videos 等
本就以 DB 为准的步骤原样返回 DB 行的 result_data。
"""
from backend.core.persistence.session_manager import SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore


def script_title(store: WorkspaceStore, session_id: str) -> str:
    """剧本展示名：大纲生成后以 outline title 为准，此前用故事逻辑阶段定的剧名"""
    outline_title = (store.read_outline(session_id) or {}).get("title", "")
    return outline_title or store.read_story_title(session_id)


def script_step_results(sm: SessionManager, store: WorkspaceStore, session_id: str) -> dict:
    """剧本会话全步骤结果（行结构 {result_data, ...}；markdown 步骤 result_data 为文件内容形状）"""
    results = {}
    for step_name, row in sm.get_step_results_map(session_id).items():
        rd = row.get("result_data") or {}
        if step_name == "story_ideation":
            rd = {**rd, "story_logic": store.read_story_logic(session_id), "title": store.read_story_title(session_id)}
        elif step_name == "story_outline":
            rd = store.read_outline(session_id) or {}
        results[step_name] = {**row, "result_data": rd}
    return results


def video_step_results(sm: SessionManager, store: WorkspaceStore, session_id: str) -> dict:
    """视频会话全步骤结果（storyboard_outline 的 result_data 为分镜文件内容形状，其余 DB 行）"""
    results = {}
    for step_name, row in sm.get_step_results_map(session_id).items():
        rd = row.get("result_data") or {}
        if step_name == "storyboard_outline":
            sel = (sm.get_step_result(session_id, "select_episode") or {}).get("result_data") or {}
            if sel.get("script_session_id") and sel.get("episode_id"):
                sb = store.read_storyboard(
                    sel["script_session_id"], sel["episode_id"], session_id,
                )
                if sb:
                    rd = sb
        results[step_name] = {**row, "result_data": rd}
    # 辅助状态（非步骤状态机）：ComfyUI 导入暂存，前端据此显示「已导入」
    comfyui_import = sm.get_step_result(session_id, "comfyui_import")
    if comfyui_import:
        results["comfyui_import"] = comfyui_import
    return results
