"""Phase 1 验证：数据层（STEPS 参数化 + script_manager DAO + 级联清理）

不依赖 agent 端点，纯 SQLite 测试。用法: uv run python test_phase1_data.py
"""
import sys
import uuid

sys.path.insert(0, ".")

from backend.core.persistence.session_manager import (
    SCRIPT_STEPS,
    VIDEO_STEPS,
    SessionManager,
)
from backend.core.persistence.script_manager import ScriptManager

DB = "data/sessions.db"


def test_session_manager_steps() -> None:
    print("=== 测试 1: STEPS 参数化 ===")
    video_sm = SessionManager(db_path=DB, steps=VIDEO_STEPS)
    script_sm = SessionManager(db_path=DB, steps=SCRIPT_STEPS)
    assert video_sm.STEPS == VIDEO_STEPS and len(video_sm.STEPS) == 5
    assert script_sm.STEPS == SCRIPT_STEPS and len(script_sm.STEPS) == 4

    # 剧本会话：创建 → 第一步 → 推进 → 清下游
    sid = f"test_script_{uuid.uuid4().hex[:8]}"
    s = script_sm.create_session(sid, workflow_type="script")
    assert s["current_step"] == "story_ideation" and s["workflow_type"] == "script"

    script_sm.save_step_result(sid, "story_ideation", {"story_logic": "x"}, success=True)
    assert script_sm.is_step_completed(sid, "story_ideation")
    script_sm.save_step_result(sid, "story_outline", {"mindmap": "# a"}, success=True)
    script_sm.save_step_result(sid, "episode_design", {"ok": True}, success=True)
    script_sm.save_step_result(sid, "lookbook_images", {"ok": True}, success=True)
    # 全部完成后 current_step 置空（_get_next_step 最后一步返回 None）
    assert not script_sm.get_session(sid)["current_step"]

    # can_execute_step：前置校验对剧本步骤生效
    sid2 = f"test_script_{uuid.uuid4().hex[:8]}"
    script_sm.create_session(sid2, workflow_type="script")
    ok, _ = script_sm.can_execute_step(sid2, "story_ideation")
    assert ok, "第 1 步应可执行"
    ok, reason = script_sm.can_execute_step(sid2, "episode_design")
    assert not ok and "尚未完成" in reason, f"前置校验失效: {reason}"

    # 清下游：outline 重做 → episode_design/lookbook 被清
    script_sm.clear_steps_after(sid, "story_outline")
    completed = script_sm.get_completed_steps(sid)
    assert "episode_design" not in completed and "story_outline" in completed

    # 视频步骤名对剧本管理器无效
    ok, reason = script_sm.can_execute_step(sid2, "select_episode")
    assert not ok, "剧本管理器不应接受视频步骤"

    for s_id in (sid, sid2):
        script_sm.delete_session(s_id)
    print("  ✓ STEPS 参数化 / 推进 / 前置校验 / 清下游")


def test_script_manager_entities() -> None:
    print("=== 测试 2: 实体注册表 + ID 分配 ===")
    sm = ScriptManager(db_path=DB)
    sid = f"test_script_{uuid.uuid4().hex[:8]}"

    # ID 分配基于落库 MAX：未落库的分配不占号（handler 内分配+插入原子完成）
    assert sm.next_entity_id(sid, "character") == "chr_001"
    e1 = sm.upsert_entity(sid, "character", "林小满", "16 岁少女，短发")
    assert e1["entity_id"] == "chr_001"
    assert sm.next_entity_id(sid, "character") == "chr_002"
    e2 = sm.upsert_entity(sid, "character", "陈默", "中年侦探")
    assert e2["entity_id"] == "chr_002"
    e3 = sm.upsert_entity(sid, "scene", "老宅书房", "昏暗，满墙照片")
    assert e3["entity_id"] == "scn_001"
    e4 = sm.upsert_entity(sid, "foreshadow", "怀表", "父亲遗留，停在 3:17")
    assert e4["entity_id"] == "fs_001"

    # 更新已有实体（ID 不变）
    e1b = sm.upsert_entity(sid, "character", "林小满", "17 岁少女，长发", meta={"age": 17}, entity_id="chr_001")
    assert e1b["entity_id"] == "chr_001" and e1b["description"] == "17 岁少女，长发"
    assert e1b["meta"] == {"age": 17}

    # 非法类型报错
    try:
        sm.upsert_entity(sid, "monster", "怪物", "")
        raise AssertionError("非法类型应报错")
    except ValueError:
        pass

    # 删除（MAX 回退后复用空号，符合 SELECT MAX+1 语义）
    assert sm.delete_entity(sid, "chr_002")
    assert sm.get_entity("chr_002") is None
    assert sm.next_entity_id(sid, "character") == "chr_002"

    # 回写定妆照引用
    lb = sm.insert_lookbook(sid, "chr_001", "a girl portrait", "林小满定妆照")
    sm.update_lookbook(lb["image_id"], {"image_path": "static/x.png", "task_status": "completed"})
    assert sm.set_entity_lookbook("chr_001", lb["image_id"], "static/x.png")
    assert sm.get_entity("chr_001")["lookbook_image_path"] == "static/x.png"
    print("  ✓ 实体 ID 分配唯一 / upsert / 删除 / 定妆照回写")


def test_script_manager_episodes() -> None:
    print("=== 测试 3: 分集设计 ===")
    sm = ScriptManager(db_path=DB)
    sid = f"test_script_{uuid.uuid4().hex[:8]}"

    ep1 = sm.upsert_episode(sid, {
        "episode_id": "ep_01", "title": "第一集", "logline": "少女返乡",
        "conflict_chain": "c1→c2", "causality_chain": "a1→a2", "ending_summary": "她发现怀表",
        "character_ids": ["chr_001"], "scene_ids": ["scn_001"],
        "clue_refs": [{"entity_id": "clu_001", "action": "plant"}],
        "foreshadow_refs": [{"entity_id": "fs_001", "action": "plant"}],
    })
    assert ep1["episode_id"] == "ep_01" and ep1["foreshadow_refs"][0]["action"] == "plant"

    # 覆写（单集重设计场景：episode_id 不变）
    sm.upsert_episode(sid, {**ep1, "title": "第一集（改）"})
    assert sm.get_episode(sid, "ep_01")["title"] == "第一集（改）"

    # 人工编辑部分字段
    sm.update_episode_fields(sid, "ep_01", {"ending_summary": "她拿走怀表"})
    assert sm.get_episode(sid, "ep_01")["ending_summary"] == "她拿走怀表"
    assert sm.get_episode(sid, "ep_01")["title"] == "第一集（改）"

    assert len(sm.list_episodes(sid)) == 1
    assert sm.delete_episode(sid, "ep_01")
    assert sm.list_episodes(sid) == []
    print("  ✓ 分集 upsert 覆写 / 部分更新 / 删除")


def test_cascade_cleanup() -> None:
    print("=== 测试 4: 级联清理（大纲重生成清下游）===")
    sm = ScriptManager(db_path=DB)
    sid = f"test_script_{uuid.uuid4().hex[:8]}"
    sm.upsert_entity(sid, "character", "甲", "")
    sm.upsert_episode(sid, {"episode_id": "ep_01", "title": "t"})
    sm.insert_lookbook(sid, "chr_001", "p", "d")
    counts = sm.delete_script_data(sid)
    assert counts == {"episodes": 1, "entities": 1, "lookbook_images": 1}, counts
    assert sm.list_entities(sid) == [] and sm.list_episodes(sid) == []
    print("  ✓ 级联清理 episodes/entities/lookbook")


if __name__ == "__main__":
    test_session_manager_steps()
    test_script_manager_entities()
    test_script_manager_episodes()
    test_cascade_cleanup()
    print("\n✅ Phase 1 数据层全部通过")
