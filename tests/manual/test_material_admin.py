"""素材管理 smoke 测试（服务层 + API 级）

运行：.venv/bin/python tests/manual/test_material_admin.py
覆盖：引用索引（实体 lb_xxx / 分镜 lookbook_lb_xxx 归一化）/ 引用中删除 409 与解除后可删 /
      删除落盘清理 + 多行共享路径不误删 / 孤儿扫描（DB/md 引用集 + uploads mtime 保护）/
      delete_files 路径穿越拒绝与引用保护 / HTTP 层四端点接线
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.errors import WorkflowError
from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.session_manager import SCRIPT_STEPS, VIDEO_STEPS, SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore
from backend.core.services import material_admin_service as svc

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


def write_file(path: Path, content: bytes = b"x" * 100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def write_segment_md(story: Path, episode_id: str, vs_id: str, index: int, title: str, refs: list[dict]):
    """手写分镜 md（frontmatter.reference_images 为素材引用）"""
    lines = ["---", f"index: {index}", f"title: {title}", "reference_images:"]
    for ref in refs:
        lines.append(f"- image_id: {ref['image_id']}")
        lines.append(f"  image_path: {ref['image_path']}")
        lines.append(f"  description: {ref.get('description', '')}")
    lines.append("---")
    lines.append(f"## 分镜大纲\n{title}的内容")
    seg_dir = story / "04-storyboards" / episode_id / vs_id
    seg_dir.mkdir(parents=True, exist_ok=True)
    seg_dir.joinpath(f"seg_{index:02d}-{title}.md").write_text("\n".join(lines), encoding="utf-8")


def build_fixture(tmp: Path):
    """搭建隔离环境：临时 DB + workspace + static 三目录，返回 (sm, store, scm, 常量注入还原函数)"""
    db_path = str(tmp / "test.db")
    sm = SessionManager(db_path=db_path, steps=SCRIPT_STEPS)
    store = WorkspaceStore(workspace_dir=tmp / "workspace", session_manager=sm)
    scm = ScriptManager(db_path=db_path)

    images_root = tmp / "static" / "images"
    videos_root = tmp / "static" / "videos"
    uploads_root = tmp / "static" / "uploads"
    for d in (images_root, videos_root, uploads_root):
        d.mkdir(parents=True, exist_ok=True)

    originals = (svc.IMAGES_ROOT, svc.VIDEOS_ROOT, svc.UPLOADS_ROOT)
    svc.IMAGES_ROOT = str(images_root)
    svc.VIDEOS_ROOT = str(videos_root)
    svc.UPLOADS_ROOT = str(uploads_root)

    def restore():
        svc.IMAGES_ROOT, svc.VIDEOS_ROOT, svc.UPLOADS_ROOT = originals

    return sm, store, scm, restore


def run_service_tests(tmp: Path):
    sm, store, scm, restore = build_fixture(tmp)
    images_root, videos_root, uploads_root = (Path(svc.IMAGES_ROOT), Path(svc.VIDEOS_ROOT), Path(svc.UPLOADS_ROOT))
    try:
        sid = "aaaaaaaa-1111-2222-3333-444444444444"
        vsid = "vvvvvvvv-1111-2222-3333-444444444444"
        sm.create_session(sid, workflow_type="script")
        sm.create_session(vsid, workflow_type="video", script_session_id=sid)
        story = store.ensure_story(sid, "草莓牛奶")
        store.set_story_title(sid, "草莓牛奶")

        # 素材落盘 + DB 行
        a_png = str(write_file(images_root / "a.png"))
        b_png = str(write_file(images_root / "b.png"))
        c_png = str(write_file(images_root / "c.png"))
        shared_png = str(write_file(images_root / "shared.png"))
        lb = scm.insert_lookbook(sid, "chr_001", prompt="p", description="定妆照A", task_status="completed", image_path=a_png)
        mat = scm.insert_episode_material(sid, "ep_01", title="夜班", task_status="completed")
        scm.update_episode_material(mat["image_id"], {"image_path": b_png, "task_status": "completed"})

        # 引用：实体锚定 lb（entity md 形态 lb_xxx）+ 分镜引用（lookbook_lb_xxx / mat_xxx 归一化）
        ent = store.upsert_entity(sid, "character", "林夏", "夜班店员")
        store.set_entity_lookbook(sid, ent["entity_id"], lb["image_id"], a_png)
        write_segment_md(story, "ep_01", "vs-abcdef12", 1, "开场", [
            {"image_id": f"lookbook_{lb['image_id']}", "image_path": a_png, "description": "引用定妆照"},
            {"image_id": mat["image_id"], "image_path": b_png, "description": "引用素材图"},
        ])

        print("== 1. 引用索引（ID 归一化：实体 lb_xxx / 分镜 lookbook_lb_xxx） ==")
        refs = svc.build_image_reference_index(store, sm)
        lb_refs = refs.get(lb["image_id"], [])
        check("定妆照被实体+分镜引用（计 2）", len(lb_refs) == 2, f"got {lb_refs}")
        check("引用类型齐全", {r["ref_type"] for r in lb_refs} == {"entity", "segment"})
        check("实体引用带名称", all(r.get("entity_name") for r in lb_refs if r["ref_type"] == "entity"))
        check("素材图被分镜引用（计 1）", len(refs.get(mat["image_id"], [])) == 1)

        print("== 2. 列表（reference_count / script_title / size） ==")
        data = svc.list_materials("lookbook", store, sm, scm)
        item = next(i for i in data["items"] if i["image_id"] == lb["image_id"])
        check("列表含引用计数", item["reference_count"] == 2)
        check("列表含剧本名", item["script_title"] == "草莓牛奶", f"got {item.get('script_title')}")
        check("列表含文件大小", item["size"] == 100, f"got {item.get('size')}")
        data = svc.list_materials("episode", store, sm, scm)
        check("分集素材列表", any(i["image_id"] == mat["image_id"] and i["reference_count"] == 1 for i in data["items"]))

        print("== 3. delete_image 引用保护与落盘清理 ==")
        try:
            svc.delete_image(lb["image_id"], store, sm, scm)
            check("引用中删除被拒", False, "未抛异常")
        except WorkflowError as e:
            check("引用中删除被拒(409)", getattr(e, "status_code", 0) == 409)
        # 解除全部引用后可删，且文件被清理
        store.set_entity_lookbook(sid, ent["entity_id"], "", "")
        write_segment_md(story, "ep_01", "vs-abcdef12", 1, "开场", [])
        result = svc.delete_image(lb["image_id"], store, sm, scm)
        check("解除引用后删除成功", result["deleted"] is True)
        check("磁盘文件已清理", not Path(a_png).exists() and result["file_deleted"] is True)
        check("DB 行已删", scm.get_lookbook(lb["image_id"]) is None)
        try:
            svc.delete_image("lb_nosuch", store, sm, scm)
            check("不存在素材 404", False, "未抛异常")
        except WorkflowError as e:
            check("不存在素材 404", getattr(e, "status_code", 0) == 404)

        print("== 4. 共享路径保护（素材库导入场景：多行同一路径） ==")
        row1 = scm.insert_lookbook(sid, "chr_001", prompt="p", task_status="completed", image_path=shared_png)
        row2 = scm.insert_lookbook(sid, "chr_002", prompt="p", task_status="completed", image_path=shared_png)
        r1 = svc.delete_image(row1["image_id"], store, sm, scm)
        check("删第一行保留共享文件", r1["file_deleted"] is False and Path(shared_png).exists())
        r2 = svc.delete_image(row2["image_id"], store, sm, scm)
        check("删最后一行清理文件", r2["file_deleted"] is True and not Path(shared_png).exists())

        print("== 5. 视频引用与列表 ==")
        vr_mp4 = str(write_file(videos_root / "vr.mp4", b"v" * 500))
        vo_mp4 = str(write_file(videos_root / "vo.mp4", b"v" * 300))
        vm = SessionManager(db_path=str(tmp / "test.db"), steps=VIDEO_STEPS)
        vm.save_step_result(vsid, "generate_videos", {
            "generated_videos": [{"video_path": vr_mp4}, {"video_path": vr_mp4}],  # 同会话两段同一视频 → 去重
            "final_video": {"video_path": vr_mp4},
        })
        vrefs = svc.build_video_reference_index(sm, store)
        check("视频引用索引（同会话去重）", len(vrefs.get(vr_mp4, [])) == 1, f"got {vrefs.get(vr_mp4)}")
        check("视频归属剧本名", vrefs[vr_mp4][0]["script_title"] == "草莓牛奶")
        data = svc.list_materials("video", store, sm, scm)
        vr_item = next(i for i in data["items"] if i["path"] == vr_mp4)
        vo_item = next(i for i in data["items"] if i["path"] == vo_mp4)
        check("被引用视频 reference_count=1", vr_item["reference_count"] == 1)
        check("孤儿视频 reference_count=0", vo_item["reference_count"] == 0)

        print("== 6. 孤儿扫描（引用集 + uploads mtime 保护） ==")
        # 此时 images: b.png(md 引用)、c.png(无引用)；videos: vr 引用 / vo 孤儿；uploads 待造
        old_png = write_file(uploads_root / "old.png")
        new_png = write_file(uploads_root / "new.png")
        now = time.time()
        os.utime(old_png, (now - 7200, now - 7200))  # 2 小时前 → 孤儿
        os.utime(new_png, (now - 60, now - 60))      # 1 分钟前 → 保护窗口内跳过
        orphans = svc.scan_orphans(store, sm, scm)
        paths = {i["path"] for i in orphans["items"]}
        check("图片孤儿仅 c.png", paths == {c_png, vo_mp4, str(old_png)}, f"got {paths}")
        check("md 仍引用的 b.png 不算孤儿", str(b_png) not in paths)
        check("DB+md 引用的视频不算孤儿", vr_mp4 not in paths)
        check("uploads mtime 保护", str(new_png) not in paths and str(old_png) in paths)
        check("total_size 汇总", orphans["total_size"] == sum(i["size"] for i in orphans["items"]))

        print("== 7. delete_files 安全校验 ==")
        result = svc.delete_files([c_png, str(old_png)], store, sm, scm)
        check("孤儿图片/上传图可删", result["deleted"] == [c_png, str(old_png)] and not Path(c_png).exists())
        result = svc.delete_files([vo_mp4, vr_mp4], store, sm, scm)
        check("孤儿视频可删、被引用视频拒删",
              result["deleted"] == [vo_mp4] and result["failed"][0]["reason"] == "视频正被工作流引用")
        secret = write_file(tmp / "secret.txt")
        result = svc.delete_files([str(secret), "../../etc/passwd"], store, sm, scm)
        check("目录外路径全部拒绝", result["deleted"] == [] and len(result["failed"]) == 2 and Path(secret).exists())
        result = svc.delete_files([str(b_png)], store, sm, scm)
        check("md 引用中的图片拒删", result["failed"][0]["reason"] == "图片正被剧本引用" and Path(b_png).exists())
    finally:
        restore()


def run_api_tests():
    print("\n== 8. HTTP 层：四端点接线（TestClient + dependency_overrides） ==")
    tmp = Path(tempfile.mkdtemp(prefix="mat_api_test_"))
    sm, store, scm, restore = build_fixture(tmp)
    images_root, uploads_root, videos_root = (Path(svc.IMAGES_ROOT), Path(svc.UPLOADS_ROOT), Path(svc.VIDEOS_ROOT))
    try:
        from fastapi.testclient import TestClient

        from backend.deps import get_script_manager, get_script_session_manager, get_workspace_store
        from backend.main import app

        app.dependency_overrides[get_script_session_manager] = lambda: sm
        app.dependency_overrides[get_script_manager] = lambda: scm
        app.dependency_overrides[get_workspace_store] = lambda: store
        client = TestClient(app)

        sid = "dddddddd-1111-2222-3333-444444444444"
        sm.create_session(sid, workflow_type="script")
        story = store.ensure_story(sid, "API测试剧本")
        ent = store.upsert_entity(sid, "character", "林冲", "教头")

        a_png = str(write_file(images_root / "api_a.png"))
        b_png = str(write_file(images_root / "api_b.png"))
        lb = scm.insert_lookbook(sid, ent["entity_id"], prompt="p", description="定妆照", task_status="completed", image_path=a_png)
        lb_free = scm.insert_lookbook(sid, ent["entity_id"], prompt="p", description="无引用", task_status="completed", image_path=b_png)
        store.set_entity_lookbook(sid, ent["entity_id"], lb["image_id"], a_png)

        resp = client.get("/api/v1/materials", params={"kind": "lookbook"})
        check("GET lookbook 200", resp.status_code == 200)
        items = resp.json()["data"]["items"]
        check("列表含引用计数", next(i for i in items if i["image_id"] == lb["image_id"])["reference_count"] == 1)
        check("kind 非法 400", client.get("/api/v1/materials", params={"kind": "bad"}).status_code == 400)

        resp = client.get("/api/v1/materials", params={"kind": "upload"})
        check("GET upload 200", resp.status_code == 200 and resp.json()["data"]["total"] == 0)

        resp = client.delete(f"/api/v1/materials/image/{lb['image_id']}")
        check("DELETE 引用中 409", resp.status_code == 409, f"got {resp.status_code}")
        resp = client.delete(f"/api/v1/materials/image/{lb_free['image_id']}")
        check("DELETE 无引用 200 + 文件清理", resp.status_code == 200 and resp.json()["data"]["file_deleted"] is True and not Path(b_png).exists())
        check("DELETE 不存在 404", client.delete("/api/v1/materials/image/lb_nosuch").status_code == 404)

        orphan_png = str(write_file(images_root / "orphan.png"))
        now = time.time()
        os.utime(orphan_png, (now - 7200, now - 7200))
        old_upload = write_file(uploads_root / "old_upload.png")
        os.utime(old_upload, (now - 7200, now - 7200))
        resp = client.get("/api/v1/materials/orphans")
        check("GET orphans 200", resp.status_code == 200)
        data = resp.json()["data"]
        check("孤儿含图片与上传", {i["path"] for i in data["items"]} == {orphan_png, str(old_upload)}, f"got {data['items']}")

        resp = client.post("/api/v1/materials/files/delete", json={"paths": [orphan_png, str(old_upload)]})
        check("POST files/delete 200", resp.status_code == 200)
        payload = resp.json()["data"]
        check("批量删除成功", sorted(payload["deleted"]) == sorted([orphan_png, str(old_upload)]) and not Path(orphan_png).exists())
        check("空 paths 合法空返回", client.post("/api/v1/materials/files/delete", json={"paths": []}).json()["data"]["deleted"] == [])
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="mat_admin_test_"))
    try:
        run_service_tests(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    run_api_tests()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
