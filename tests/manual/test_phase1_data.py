"""Phase 1 验证：数据层（STEPS 参数化 + 文件化工作区 + 生图任务表 + 级联清理）

不依赖 agent 端点。用法: uv run python tests/manual/test_phase1_data.py
实体/分集读写已迁 WorkspaceStore（markdown 权威源）；ScriptManager 只剩
核心素材/分集素材图两张任务状态机表。全程使用临时目录/临时 DB，不污染
data/sessions.db 与 workspace/。
"""
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.persistence.session_manager import (
    SCRIPT_STEPS,
    VIDEO_STEPS,
    SessionManager,
)
from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.workspace_store import WorkspaceStore


def test_session_manager_steps(sm: SessionManager) -> None:
    print("=== 测试 1: STEPS 参数化 ===")
    video_sm = SessionManager(db_path=sm.db_path, steps=VIDEO_STEPS)
    script_sm = SessionManager(db_path=sm.db_path, steps=SCRIPT_STEPS)
    assert video_sm.STEPS == VIDEO_STEPS and len(video_sm.STEPS) == 4
    assert script_sm.STEPS == SCRIPT_STEPS and len(script_sm.STEPS) == 4

    # 剧本会话：创建 → 第一步 → 推进 → 清下游
    sid = uuid.uuid4().hex
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
    sid2 = uuid.uuid4().hex
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


def test_workspace_entities(store: WorkspaceStore, sm: SessionManager) -> str:
    print("=== 测试 2: 实体注册表（WorkspaceStore）+ ID 分配 ===")
    sid = uuid.uuid4().hex
    sm.create_session(sid, workflow_type="script")

    # ID 分配基于全工作区 glob MAX+1（全局唯一，与旧 DB 语义一致）
    e1 = store.upsert_entity(sid, "character", "林小满", "16 岁少女，短发")
    assert e1["entity_id"] == "chr_001"
    e2 = store.upsert_entity(sid, "character", "陈默", "中年侦探")
    assert e2["entity_id"] == "chr_002"
    e3 = store.upsert_entity(sid, "scene", "老宅书房", "昏暗，满墙照片")
    assert e3["entity_id"] == "scn_001"
    e4 = store.upsert_entity(sid, "foreshadow", "怀表", "父亲遗留，停在 3:17")
    assert e4["entity_id"] == "fs_001"

    # 更新已有实体（ID 不变）
    e1b = store.upsert_entity(sid, "character", "林小满", "17 岁少女，长发", meta={"age": 17}, entity_id="chr_001")
    assert e1b["entity_id"] == "chr_001" and e1b["description"] == "17 岁少女，长发"
    assert e1b["meta"] == {"age": 17}

    # 非法类型报错
    try:
        store.upsert_entity(sid, "monster", "怪物", "")
        raise AssertionError("非法类型应报错")
    except ValueError:
        pass

    # 删除
    assert store.delete_entity(sid, "chr_002")
    assert store.get_entity(sid, "chr_002") is None

    # 回写核心素材引用（任务本体在 DB，文件只存引用）
    assert store.set_entity_lookbook(sid, "chr_001", "lb_x", "static/x.png")
    assert store.get_entity(sid, "chr_001")["lookbook_image_path"] == "static/x.png"
    print("  ✓ 实体 ID 分配唯一 / upsert / 删除 / 核心素材回写")
    return sid


def test_workspace_episodes(store: WorkspaceStore, sid: str) -> None:
    print("=== 测试 3: 分集设计（WorkspaceStore）===")
    ep1 = store.upsert_episode(sid, {
        "episode_id": "ep_01", "title": "第一集", "logline": "少女返乡",
        "conflict_chain": "c1→c2", "causality_chain": "a1→a2", "ending_summary": "她发现怀表",
        "character_ids": ["chr_001"], "scene_ids": ["scn_001"],
        "clue_refs": [{"entity_id": "clu_001", "action": "plant"}],
        "foreshadow_refs": [{"entity_id": "fs_001", "action": "plant"}],
    })
    assert ep1["episode_id"] == "ep_01" and ep1["foreshadow_refs"][0]["action"] == "plant"

    # 覆写（单集重设计场景：episode_id 不变）
    store.upsert_episode(sid, {**ep1, "title": "第一集（改）"})
    assert store.get_episode(sid, "ep_01")["title"] == "第一集（改）"

    # 人工编辑部分字段
    store.update_episode_fields(sid, "ep_01", {"ending_summary": "她拿走怀表"})
    assert store.get_episode(sid, "ep_01")["ending_summary"] == "她拿走怀表"
    assert store.get_episode(sid, "ep_01")["title"] == "第一集（改）"

    assert len(store.list_episodes(sid)) == 1
    assert store.delete_episode(sid, "ep_01")
    assert store.list_episodes(sid) == []
    print("  ✓ 分集 upsert 覆写 / 部分更新 / 删除")


def test_cascade_cleanup(store: WorkspaceStore, sm: SessionManager, scm: ScriptManager) -> str:
    print("=== 测试 4: 级联清理（大纲重生成清下游）===")
    sid = uuid.uuid4().hex
    sm.create_session(sid, workflow_type="script")
    store.upsert_entity(sid, "character", "甲", "")
    store.upsert_episode(sid, {"episode_id": "ep_01", "title": "t"})
    lb = scm.insert_lookbook(sid, "chr_001", "p", "d")
    mat = scm.insert_episode_material(sid, "ep_01", title="t")

    # 文件侧：清空分集与实体（02/03），返回 episodes/entities 计数
    counts = store.delete_story_content(sid)
    assert counts == {"episodes": 1, "entities": 1}, counts
    assert store.list_entities(sid) == [] and store.list_episodes(sid) == []

    # DB 侧：核心素材/分集素材图任务表，返回 lookbook_images/episode_material_images 计数
    # （keep_completed_lookbooks 默认 False → lookbook_images_kept 恒 0）
    db_counts = scm.delete_script_data(sid)
    assert db_counts == {"lookbook_images": 1, "lookbook_images_kept": 0, "episode_material_images": 1}, db_counts
    assert scm.list_lookbook(sid) == [] and scm.list_episode_materials(sid) == []
    assert scm.get_lookbook(lb["image_id"]) is None
    assert scm.get_episode_material(mat["image_id"]) is None
    print("  ✓ 级联清理 episodes/entities（文件）+ lookbook/materials（DB）")
    return sid


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="phase1_data_test_"))
    try:
        sm = SessionManager(db_path=str(tmp / "test.db"), steps=SCRIPT_STEPS)
        scm = ScriptManager(db_path=str(tmp / "test.db"))
        # 注入独立空库 ScriptManager：ID 分配并入 lookbook 保留行防撞，
        # 不注入会延迟取 deps 单例（项目真实 DB，含历史 lookbook 行），chr_001 断言漂移
        store = WorkspaceStore(workspace_dir=tmp / "workspace", session_manager=sm, script_manager=scm)

        test_session_manager_steps(sm)
        sid_entities = test_workspace_entities(store, sm)
        test_workspace_episodes(store, sid_entities)
        sid_cascade = test_cascade_cleanup(store, sm, scm)

        # 清理临时数据：删 story 树（连带锚点清除）+ 会话行
        for s_id in (sid_entities, sid_cascade):
            assert store.delete_story(s_id)
            sm.delete_session(s_id)
        assert store.story_dir(sid_entities) is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n✅ Phase 1 数据层全部通过")


if __name__ == "__main__":
    main()
