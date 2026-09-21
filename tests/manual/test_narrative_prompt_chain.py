"""叙事链路注入手工 smoke 测试（会话审查修复回归）

运行：.venv/bin/python tests/manual/test_narrative_prompt_chain.py
覆盖：_auto_global_prompt 容错与截断（None/异常/正则跨行/句号截断/logline 截断）/
      分镜提示词 drama_section 边界（mindmap 空/首末段/缺 index 键）/
      大纲集数正则对新格式（4 全局分支 + 「第N集」字样防护）的计数正确性
"""
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.errors import WorkflowError
from backend.core.workflows.video_workflow import VideoCreationWorkflowV2

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def make_workflow(store=None, selected=None, selected_exc=None):
    """构造最小 VideoCreationWorkflowV2（不触发 __init__ 依赖）"""
    sm = MagicMock()
    if selected_exc:
        sm.get_step_result.side_effect = selected_exc
    elif selected is not None:
        sm.get_step_result.return_value = {"result_data": selected}
    wf = VideoCreationWorkflowV2.__new__(VideoCreationWorkflowV2)
    wf.session_manager = sm
    wf.store = store if store is not None else MagicMock()
    return wf


def run_auto_global_prompt():
    print("== _auto_global_prompt 容错与截断 ==")
    # 1. 无选集（WorkflowError）→ 空串
    wf = make_workflow(selected_exc=WorkflowError("no step"))
    check("无选集返回空串", wf._auto_global_prompt("s") == "")

    # 2. 选集读取抛非 WorkflowError（如 KeyError）→ 空串（best-effort）
    wf = make_workflow(selected_exc=KeyError("boom"))
    check("选集异常不炸主流程", wf._auto_global_prompt("s") == "")

    # 3. 空选集信息 → 空串
    wf = make_workflow(selected={})
    check("空选集返回空串", wf._auto_global_prompt("s") == "")

    # 4. get_episode 抛存储异常 → 仍产出基调部分
    store = MagicMock()
    store.get_episode.side_effect = ValueError("bad episode id")
    store.read_story_logic.return_value = "情感基调与题材：悬疑；情绪由紧到松。主题内核：被拖带的字段"
    wf = make_workflow(store=store, selected={"script_session_id": "sid", "episode_id": "ep_01"})
    out = wf._auto_global_prompt("s")
    check("episode 异常时基调仍产出", "全剧基调：悬疑；情绪由紧到松。" in out)

    # 5. 正则不跨行吸入下一行正文
    store = MagicMock()
    store.get_episode.return_value = None
    store.read_story_logic.return_value = "情感基调与题材：\n下一行正文不该被吸入"
    wf = make_workflow(store=store, selected={"script_session_id": "sid", "episode_id": "ep_01"})
    out = wf._auto_global_prompt("s")
    check("空行值不吸下一行", "下一行正文" not in out)

    # 6. 句号截断丢弃同行拖带的「主题内核」
    store = MagicMock()
    store.get_episode.return_value = {"logline": "梗概" * 100}
    store.read_story_logic.return_value = "情感基调与题材：东方玄幻＋写实村镇；情绪由辛酸走向释放。主题内核：一个人押上一生"
    wf = make_workflow(store=store, selected={"script_session_id": "sid", "episode_id": "ep_01"})
    out = wf._auto_global_prompt("s")
    check("句号截断砍掉主题内核", "主题内核" not in out and "情绪由辛酸走向释放。" in out)

    # 7. logline 截断 200
    check("logline 截断到 200 字", "梗概" in out and len(out.split("\n")[0]) <= 210)


def run_drama_section():
    print("== drama_section 边界（generate_segment_prompt 注入） ==")
    from backend.core.agents.storyboard import StoryboardWorkflow

    def build(mindmap, segments, index):
        """抽取 drama_section 构建逻辑的最小重现（与 storyboard.py 保持一致的正则/边界）"""
        segments_count = len(segments)
        drama_section = ""
        if mindmap and mindmap.strip():
            by_index = {s.get("index"): s for s in segments}
            position_parts = [f"本分镜位置：第 {index + 1} 段 / 共 {segments_count} 段"]
            if by_index.get(index - 1):
                position_parts.append(f"上一段：《{by_index.get(index - 1).get('title', '')}》")
            if by_index.get(index + 1):
                position_parts.append(f"下一段：《{by_index.get(index + 1).get('title', '')}》")
            drama_section = "\n".join(position_parts)
        return drama_section

    segs = [{"index": 0, "title": "A"}, {"index": 2, "title": "C"}]  # index=1 缺失
    check("mindmap 为 None 不炸", build(None, segs, 0) == "")
    check("mindmap 空串不炸", build("", segs, 0) == "")
    out = build("# 标题\n## 第一幕", segs, 0)
    check("首段无上一段", "上一段" not in out and "第 1 段 / 共 2 段" in out)
    out = build("# 标题", segs, 1)
    check("缺 index 键的邻段被跳过", "上一段：《A》" in out and "下一段：《C》" in out)
    check("StoryboardWorkflow 可导入", StoryboardWorkflow is not None)


EPISODE_RE = re.compile(r"^#{2,3}\s*(?:第\s*\d+\s*集|EP\s*\d+)", re.M)


def run_episode_count():
    print("== 集数正则对新格式的计数 ==")
    outline = """# 试炼之剧
## 核心命题：测试
## 叙事策略
### 手法：倒叙
## 观众设计
### 视点人物：主角
### 认知锚点：前史→（第1集闪回建立）；规矩→（第2集台词）
### 视觉母题：龙鳞微光——第1集埋设，第8集收束
## 三线设计
### 叙事线：主轴
## 第 1 集：开场
### 视觉锚点：画面
### 观众认知：新建立前史；依赖=无
## 第 2 集：推进
## 第 3 集：转折
## 第 4 集：高潮
## 第 5 集：收束"""
    count = len(EPISODE_RE.findall(outline))
    check("5 集不被全局分支污染", count == 5, f"实际 {count}")
    # 防护失效场景（子节点以「第N集」开头）作为回归警示：prompt 已加防护句
    polluted = outline.replace("### 认知锚点：前史→（第1集闪回建立）", "### 第1集：前史")
    count2 = len(EPISODE_RE.findall(polluted))
    check("防护失效时正则会误计（回归警示）", count2 == 6, f"实际 {count2}")


def main():
    try:
        run_auto_global_prompt()
        run_drama_section()
        run_episode_count()
    finally:
        print(f"\n结果: {PASS} 通过, {FAIL} 失败")
        sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
