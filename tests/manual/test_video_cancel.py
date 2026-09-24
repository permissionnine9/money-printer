"""视频生成「停止生成」回归测试（真取消 + 启动回收）

运行：.venv/bin/python tests/manual/test_video_cancel.py
覆盖：wait_for_result 取消检测与远程中断 / _save_video_cancelled 落盘（pending→cancelled、
      备份字段保留、_cancelled 清除）/ recover_stale_generations 启动回收 /
      _execute_imported_videos 全链路取消落盘
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.session_manager import SCRIPT_STEPS, VIDEO_STEPS, SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore
from backend.core.services.comfyui_service import ComfyUIClient, GenerationCancelledError
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


def make_workflow(tmp: Path):
    """独立空库上的 workflow + 视频 SessionManager"""
    db = str(tmp / "test.db")
    script_sm = SessionManager(db_path=db, steps=SCRIPT_STEPS)
    store = WorkspaceStore(
        workspace_dir=tmp / "ws", session_manager=script_sm,
        script_manager=ScriptManager(db_path=db),
    )
    video_sm = SessionManager(db_path=db, steps=VIDEO_STEPS)
    return VideoCreationWorkflowV2(session_manager=video_sm, store=store), video_sm


def seed_generating(video_sm: SessionManager, sid: str, *, cancelled: bool = False):
    """预置一个 mark_videos_generating 形状的生成中状态（2 段 pending，段 0 带备份）"""
    video_sm.save_step_result(sid, "generate_videos", {
        "generated_videos": [
            {"segment_index": 0, "task_status": "pending", "_old_video_path": "static/old.mp4"},
            {"segment_index": 1, "task_status": "pending"},
        ],
        "video_count": 2,
        "segment_indexes": [0, 1],
        "success_count": 0,
        "failed_count": 0,
        "final_video": None,
        "_backed_up_count": 1,
        "_generating": True,
        "_success": False,
        **({"_cancelled": True} if cancelled else {}),
    }, success=False)


def test_wait_for_result_cancel():
    print("== 1. wait_for_result 取消检测 ==")
    client = ComfyUIClient("http://127.0.0.1:1")  # 请求全部打桩，不实际联网
    interrupt_calls = []

    async def fake_history(prompt_id):
        return {}

    async def fake_interrupt():
        interrupt_calls.append(1)

    client.get_history = fake_history
    client.interrupt = fake_interrupt

    try:
        asyncio.run(client.wait_for_result(
            "pid", max_wait=10, poll_interval=0.01, cancel_check=lambda: True,
        ))
        check("取消标志命中应抛 GenerationCancelledError", False)
    except GenerationCancelledError:
        check("取消标志命中抛 GenerationCancelledError", True)
    check("取消时请求了远程中断", len(interrupt_calls) == 1)

    async def done_history(prompt_id):
        return {"status": {"completed": True, "status_str": "success"}}

    client.get_history = done_history
    history = asyncio.run(client.wait_for_result(
        "pid", max_wait=10, poll_interval=0.01, cancel_check=lambda: False,
    ))
    check("未取消时正常返回 history", history["status"]["completed"] is True)


def test_save_video_cancelled(tmp: Path):
    print("== 2. _save_video_cancelled 落盘 ==")
    wf, video_sm = make_workflow(tmp)
    sid = "bbbbbbbb-1111-2222-3333-444444444444"
    video_sm.create_session(sid, workflow_type="video")
    seed_generating(video_sm, sid, cancelled=True)

    ret = wf._save_video_cancelled(sid)
    data = video_sm.get_step_result(sid, "generate_videos")["result_data"]
    statuses = [v["task_status"] for v in data["generated_videos"]]
    check("pending 全部落盘为 cancelled", statuses == ["cancelled", "cancelled"], str(statuses))
    check("_generating 退出", data["_generating"] is False)
    check("_cancelled 标志消费后清除", data.get("_cancelled") is False)
    check("备份字段保留（恢复备份仍可用）",
          data["generated_videos"][0].get("_old_video_path") == "static/old.mp4"
          and data["_backed_up_count"] == 1)
    check("返回值语义为已停止", ret["success"] is False and ret["message"] == "视频生成已停止")


def test_recover_stale_generations(tmp: Path):
    print("== 3. 启动回收悬挂状态 ==")
    wf, video_sm = make_workflow(tmp)
    stale_sid = "cccccccc-1111-2222-3333-444444444444"
    done_sid = "dddddddd-1111-2222-3333-444444444444"
    video_sm.create_session(stale_sid, workflow_type="video")
    video_sm.create_session(done_sid, workflow_type="video")
    seed_generating(video_sm, stale_sid)
    video_sm.save_step_result(done_sid, "generate_videos", {
        "generated_videos": [{"segment_index": 0, "task_status": "completed"}],
        "video_count": 1, "segment_indexes": [0], "success_count": 1,
        "_generating": False, "_success": True,
    }, success=True)

    recovered = wf.recover_stale_generations()
    stale = video_sm.get_step_result(stale_sid, "generate_videos")["result_data"]
    done = video_sm.get_step_result(done_sid, "generate_videos")["result_data"]
    check("只回收悬挂会话，返回 1", recovered == 1, f"recovered={recovered}")
    check("悬挂会话落盘为已停止",
          stale["_generating"] is False and stale["generated_videos"][0]["task_status"] == "cancelled")
    check("已完成会话不受影响", done["_generating"] is False and done["generated_videos"][0]["task_status"] == "completed")


def test_execute_imported_cancel_chain(tmp: Path):
    print("== 4. 执行链路取消全链路落盘 ==")
    wf, video_sm = make_workflow(tmp)
    sid = "eeeeeeee-1111-2222-3333-444444444444"
    video_sm.create_session(sid, workflow_type="video")
    seed_generating(video_sm, sid)

    class CancelledService:
        """execute_imported 直接抛取消（模拟轮询中检测到 _cancelled）"""
        async def execute_imported(self, segments, workflow, timeline, cancel_check=None):
            raise GenerationCancelledError("pid")

    wf.comfyui_service = CancelledService()
    ret = asyncio.run(wf._execute_imported_videos(sid, {
        "segments": [], "workflow": {}, "timeline_data": {"fps": 24}, "segment_indexes": [0, 1],
    }))
    data = video_sm.get_step_result(sid, "generate_videos")["result_data"]
    check("链路返回已停止而非失败", ret["success"] is False and "已停止" in ret["message"], str(ret))
    check("DB 落盘为已停止（cancelled + 退出 generating）",
          data["_generating"] is False
          and [v["task_status"] for v in data["generated_videos"]] == ["cancelled", "cancelled"])


def main():
    tmp = Path(tempfile.mkdtemp(prefix="video_cancel_test_"))
    try:
        test_wait_for_result_cancel()
        test_save_video_cancelled(tmp / "t2")
        test_recover_stale_generations(tmp / "t3")
        test_execute_imported_cancel_chain(tmp / "t4")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
