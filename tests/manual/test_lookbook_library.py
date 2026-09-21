"""核心素材素材库 smoke 测试（存储层 + API 级）

运行：.venv/bin/python tests/manual/test_lookbook_library.py
覆盖：delete_script_data 保留语义（5 种任务状态）/ list_completed_lookbooks 跨会话过滤 /
      insert_lookbook 新参（image_path/meta）落库 / cascade_regenerate 级联保留 /
      HTTP 层：GET lookbook/library 分组与实体名映射 / POST lookbook/import 复制锚定与失败分支
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.session_manager import SCRIPT_STEPS, SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore
from backend.core.services.regeneration import cascade_regenerate

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


def seed_status_rows(scm: ScriptManager, sid: str, entity_id: str) -> dict[str, str]:
    """造 5 种状态的 lookbook 行，返回 {状态: image_id}"""
    ids = {}
    for key, status, path in [
        ("completed", "completed", "https://img.example/a.png"),
        ("completed_nopath", "completed", ""),  # completed 但无 path
        ("pending", "pending", ""),
        ("processing", "processing", ""),
        ("failed", "failed", ""),
    ]:
        row = scm.insert_lookbook(sid, entity_id, prompt=f"p-{status}", task_status=status)
        if path:
            scm.update_lookbook(row["image_id"], {"image_path": path})
        ids[key] = row["image_id"]
    return ids


def main():
    tmp = Path(tempfile.mkdtemp(prefix="lb_library_test_"))
    db_path = str(tmp / "test.db")
    sm = SessionManager(db_path=db_path, steps=SCRIPT_STEPS)
    scm = ScriptManager(db_path=db_path)
    store = WorkspaceStore(workspace_dir=tmp / "workspace", session_manager=sm, script_manager=scm)
    try:
        run(scm, sm, store)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    run_api_tests()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


def run_api_tests():
    """HTTP 层：chdir 到 tmp 使相对路径 data/sessions.db、workspace/ 落在隔离目录"""
    print("\n== 6. HTTP 层：素材库查询 / 导入（TestClient） ==")
    tmp = Path(tempfile.mkdtemp(prefix="lb_api_test_"))
    old_cwd = os.getcwd()
    os.chdir(tmp)
    (tmp / "static").mkdir()  # main.py 挂载 StaticFiles 要求 static/ 存在
    try:
        from fastapi.testclient import TestClient

        from backend.deps import get_script_manager
        from backend.main import app

        client = TestClient(app)
        scm = get_script_manager()

        sid = client.post("/api/v1/script-sessions", json={}).json()["data"]["session_id"]
        other = client.post("/api/v1/script-sessions", json={}).json()["data"]["session_id"]
        ent_a = client.post(
            f"/api/v1/script-sessions/{sid}/entities",
            json={"entity_type": "character", "name": "林冲", "description": "八十万禁军教头"},
        ).json()["data"]
        ent_b = client.post(
            f"/api/v1/script-sessions/{other}/entities",
            json={"entity_type": "character", "name": "武松", "description": "打虎英雄"},
        ).json()["data"]
        ent_s = client.post(
            f"/api/v1/script-sessions/{other}/entities",
            json={"entity_type": "scene", "name": "野猪林", "description": "大雪覆盖的松林"},
        ).json()["data"]

        src = scm.insert_lookbook(other, ent_b["entity_id"], prompt="p", description="武松三视图", task_status="completed")
        scm.update_lookbook(src["image_id"], {"image_path": "https://img.example/wusong.png"})
        src_scene = scm.insert_lookbook(other, ent_s["entity_id"], prompt="p", description="野猪林全景",
                                        task_status="completed", image_path="https://img.example/scene.png",
                                        meta={"entity_type": "scene"})
        scm.insert_lookbook(sid, "chr_999", prompt="p", description="当前剧本历史素材", task_status="completed",
                            image_path="https://img.example/old.png")
        pend = scm.insert_lookbook(sid, ent_a["entity_id"], prompt="p", task_status="pending")

        # --- GET library ---
        resp = client.get(f"/api/v1/script-sessions/{sid}/lookbook/library")
        check("library 200", resp.status_code == 200)
        data = resp.json()["data"]
        check("当前剧本组排第一", data["groups"][0]["key"] == "current")
        cur = data["groups"][0]["materials"]
        check("历史素材 entity_exists=False", len(cur) == 1 and cur[0]["entity_exists"] is False and cur[0]["entity_id"] == "chr_999")
        other_group = data["groups"][1]
        src_material = next(m for m in other_group["materials"] if m["image_id"] == src["image_id"])
        check("其他剧本组实体名映射", src_material["entity_name"] == "武松" and src_material["entity_exists"] is True)
        check("library 不含未完成行", all(m["image_id"] != pend["image_id"] for g in data["groups"] for m in g["materials"]))
        check("library 会话不存在 404", client.get("/api/v1/script-sessions/no-such/lookbook/library").status_code == 404)

        # --- POST import 成功 ---
        resp = client.post(
            f"/api/v1/script-sessions/{sid}/lookbook/import",
            json={"entity_id": ent_a["entity_id"], "source_image_id": src["image_id"]},
        )
        check("import 200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:120]}")
        payload = resp.json()["data"]
        check("复制行 completed + 同 URL",
              payload["image"]["task_status"] == "completed" and payload["image"]["image_path"] == "https://img.example/wusong.png")
        check("meta.imported_from 溯源",
              payload["image"]["meta"].get("imported_from", {}).get("image_id") == src["image_id"])
        check("实体锚点已回写", payload["entity"]["lookbook_image_id"] == payload["image"]["image_id"])
        ent_after = client.get(f"/api/v1/script-sessions/{sid}/entities").json()["data"]["entities"]
        check("GET entities 反映锚点",
              next(e for e in ent_after if e["entity_id"] == ent_a["entity_id"])["lookbook_image_id"] == payload["image"]["image_id"])
        check("import 后 library 含新行（当前剧本组）",
              any(m["image_id"] == payload["image"]["image_id"]
                  for m in client.get(f"/api/v1/script-sessions/{sid}/lookbook/library").json()["data"]["groups"][0]["materials"]))

        # --- import 失败分支 ---
        resp = client.post(
            f"/api/v1/script-sessions/{sid}/lookbook/import",
            json={"entity_id": ent_a["entity_id"], "source_image_id": "lb_nosuch"},
        )
        check("源图不存在 404", resp.status_code == 404, f"got {resp.status_code}")
        resp = client.post(
            f"/api/v1/script-sessions/{sid}/lookbook/import",
            json={"entity_id": ent_a["entity_id"], "source_image_id": pend["image_id"]},
        )
        check("未完成素材 400", resp.status_code == 400, f"got {resp.status_code}")
        resp = client.post(
            f"/api/v1/script-sessions/{sid}/lookbook/import",
            json={"entity_id": "chr_888", "source_image_id": src["image_id"]},
        )
        check("实体不存在 404", resp.status_code == 404, f"got {resp.status_code}")
        resp = client.post(
            f"/api/v1/script-sessions/{sid}/lookbook/import",
            json={"entity_id": "bad_id", "source_image_id": src["image_id"]},
        )
        check("entity_id 格式非法 422", resp.status_code == 422, f"got {resp.status_code}")
        resp = client.post(
            f"/api/v1/script-sessions/{sid}/lookbook/import",
            json={"entity_id": ent_a["entity_id"], "source_image_id": src_scene["image_id"]},
        )
        check("场景素材绑人物实体 400（类型不匹配）", resp.status_code == 400, f"got {resp.status_code} {resp.text[:80]}")

        # --- 通用删除端点级联清理（行为变更：剧本会话经通用端点删除也清 lookbook/story） ---
        resp = client.delete(f"/api/v1/sessions/{other}")
        check("通用端点可删剧本会话（不校验 workflow_type）", resp.status_code in (200, 204), f"got {resp.status_code}")
        check("lookbook 行已级联删除（不再残留孤儿）", not scm.get_lookbook(src["image_id"]))

        # --- alive 过滤（防御）：删除中途失败残留的孤儿行不进素材库 ---
        dead_sid = "deaddead-1111-2222-3333-444444444444"
        scm.insert_lookbook(dead_sid, "chr_777", prompt="p", task_status="completed",
                            image_path="https://img.example/dead.png")
        keys_after = [g["key"] for g in client.get(f"/api/v1/script-sessions/{sid}/lookbook/library").json()["data"]["groups"]]
        check("死会话素材不进素材库", dead_sid not in keys_after and "current" in keys_after, f"got {keys_after}")
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp, ignore_errors=True)


def run(scm: ScriptManager, sm: SessionManager, store: WorkspaceStore):
    sid = "aaaaaaaa-1111-2222-3333-444444444444"
    other = "bbbbbbbb-1111-2222-3333-444444444444"
    sm.create_session(sid, workflow_type="script")
    sm.create_session(other, workflow_type="script")

    print("== 1. insert_lookbook 新参（image_path / meta）落库 ==")
    row = scm.insert_lookbook(
        sid, "chr_001", prompt="p1", description="d1",
        task_status="completed", image_path="https://img.example/x.png",
        meta={"imported_from": {"image_id": "lb_src"}},
    )
    check("image_path 落库", row["image_path"] == "https://img.example/x.png")
    check("meta 落库", row["meta"] == {"imported_from": {"image_id": "lb_src"}})

    print("== 2. list_completed_lookbooks 跨会话过滤 ==")
    ids = seed_status_rows(scm, other, "chr_002")
    done = scm.list_completed_lookbooks()
    done_ids = {r["image_id"] for r in done}
    check("含本会话 completed+path 行", row["image_id"] in done_ids)
    check("含其他会话 completed+path 行", ids["completed"] in done_ids)
    check("排除 completed-无path", ids["completed_nopath"] not in done_ids)
    check("排除 pending/processing/failed",
          ids["pending"] not in done_ids and ids["processing"] not in done_ids and ids["failed"] not in done_ids)

    print("== 3. delete_script_data keep 语义（保留 completed+path） ==")
    counts = scm.delete_script_data(other, keep_completed_lookbooks=True)
    remaining = {r["image_id"] for r in scm.list_lookbook(other)}
    check("保留 completed+path 行", ids["completed"] in remaining)
    check("删 completed-无path 行", ids["completed_nopath"] not in remaining)
    check("删 pending/processing/failed 行",
          ids["pending"] not in remaining and ids["processing"] not in remaining and ids["failed"] not in remaining)
    check("返回 lookbook_images_kept", counts.get("lookbook_images_kept") == 1, f"got {counts}")

    print("== 4. delete_script_data 默认全删 ==")
    scm.delete_script_data(sid)
    check("默认模式全删", scm.list_lookbook(sid) == [])

    print("== 5. cascade_regenerate 级联保留 ==")
    sid2 = "cccccccc-1111-2222-3333-444444444444"
    sm.create_session(sid2, workflow_type="script")
    keep_row = scm.insert_lookbook(sid2, "chr_003", prompt="p", task_status="completed")
    scm.update_lookbook(keep_row["image_id"], {"image_path": "https://img.example/keep.png"})
    scm.insert_lookbook(sid2, "chr_003", prompt="p2", task_status="processing")
    cascade_regenerate(sm, store, scm, sid2, "story_outline")
    rows = scm.list_lookbook(sid2)
    check("级联后保留 completed 行", [r["image_id"] for r in rows] == [keep_row["image_id"]], f"got {[r['image_id'] for r in rows]}")
    check("级联后 processing 行已删", all(r["task_status"] == "completed" for r in rows))

    print("== 6. 实体 ID 防撞：DB 保留行占用 ID 段 ==")
    # 级联保留了 chr_003 行且实体文件已清（delete_story_content）：
    # 新建实体须跳过 chr_003，否则新角色复用旧 ID → 保留行旧图被当作新实体素材（跨代错配）
    new_ent = store.upsert_entity(sid2, "character", "新角色", description="ID 防撞验证")
    check("新建实体跳过 DB 保留行 ID", new_ent["entity_id"] == "chr_004", f"got {new_ent['entity_id']}")
    check("max_entity_seq 返回保留行最大序号", scm.max_entity_seq("chr") == 3, f"got {scm.max_entity_seq('chr')}")


if __name__ == "__main__":
    main()
