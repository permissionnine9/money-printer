"""WorkspaceStore 手工 smoke 测试（存储层 + 审查修复回归）

运行：.venv/bin/python tests/manual/test_workspace_store.py
覆盖：story 生命周期 / story_logic / outline（剧名正名）/ episodes / entities（全局 ID）/
      storyboard（写读/替换/单镜更新）/ 级联清理 / MAP 渲染 / 并发写 /
      审查修复回归（ID 白名单 / 正文 ## 转义往返 / 并发 ID 不撞号 / 跨会话隔离）
"""
import shutil
import sys
import tempfile
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.persistence.session_manager import SCRIPT_STEPS, SessionManager
from backend.core.persistence.workspace_store import WorkspaceStore, WorkspaceStoreError

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


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ws_store_test_"))
    sm = SessionManager(db_path=str(tmp / "test.db"), steps=SCRIPT_STEPS)
    store = WorkspaceStore(workspace_dir=tmp / "workspace", session_manager=sm)
    try:
        run(store, sm, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


def run(store: WorkspaceStore, sm: SessionManager, tmp: Path):
    sid = "aaaaaaaa-1111-2222-3333-444444444444"
    sm.create_session(sid, workflow_type="script")

    print("== 1. story 生命周期 ==")
    story = store.ensure_story(sid)
    check("ensure_story 创建目录", story.is_dir())
    check("子目录齐全", all((story / d).is_dir() for d in (
        "00-ideation", "01-outline", "02-episodes", "03-entities", "04-storyboards")))
    check("MAP.md 已渲染", (story / "MAP.md").is_file())
    check("锚点回写", sm.get_session(sid)["workspace_path"] == story.name)
    check("story_dir 定位一致", store.story_dir(sid) == story)
    check("ensure 幂等", store.ensure_story(sid) == story)
    check("story_title 未命名", store.story_title(sid) == "未命名剧本")

    print("== 2. story_logic ==")
    store.write_story_logic(sid, "一个雨夜复仇的故事逻辑全集。")
    check("读回一致", store.read_story_logic(sid) == "一个雨夜复仇的故事逻辑全集。")
    check("空 story 读空", store.read_story_logic("ffffffff-0000-0000-0000-000000000000") == "")

    print("== 3. outline（剧名正名 rename） ==")
    mindmap = "# 林小雨的雨夜\n## 第 1 集\n- 开局\n- 高潮"
    outline = store.write_outline(sid, mindmap, requirements={"episode_count": 1})
    check("mindmap 读回", outline["mindmap"] == mindmap)
    check("title 提取", outline["title"] == "林小雨的雨夜")
    renamed = store.story_dir(sid)
    check("story 随剧名 rename", renamed.name.startswith("林小雨的雨夜-"))
    check("锚点随 rename 更新", sm.get_session(sid)["workspace_path"] == renamed.name)
    check("edited 初始 False", outline["edited"] is False)
    updated = store.update_outline(sid, "# 林小雨的雨夜\n## 第 1 集\n- 改过的开局")
    check("人工编辑 edited=True", updated["edited"] is True)

    print("== 4. episodes ==")
    ep = {
        "episode_id": "ep_01", "title": "巷口初遇", "logline": "雨夜巷口的初遇",
        "conflict_chain": "欲望→阻力", "causality_chain": "承接开局", "ending_summary": "她转身离开",
        "story_progress": "开局局面→推进→集尾状态",
        "character_ids": ["chr_001"], "scene_ids": ["scn_001"],
        "clue_refs": [{"entity_id": "clu_001", "action": "plant"}],
        "foreshadow_refs": [{"entity_id": "fs_001", "action": "plant"}],
    }
    saved = store.upsert_episode(sid, ep)
    check("row 键齐全（对齐 DB）", set(saved.keys()) == {
        "episode_id", "script_session_id", "title", "logline", "conflict_chain", "causality_chain",
        "ending_summary", "story_progress", "character_ids", "scene_ids", "clue_refs",
        "foreshadow_refs", "meta", "edited", "created_at", "updated_at"})
    check("文本字段往返", saved["logline"] == "雨夜巷口的初遇" and saved["ending_summary"] == "她转身离开")
    check("refs 往返", saved["foreshadow_refs"] == [{"entity_id": "fs_001", "action": "plant"}])
    check("script_session_id 注入", saved["script_session_id"] == sid)
    check("文件名规范", (store.story_dir(sid) / "02-episodes" / "ep_01-巷口初遇.md").is_file())

    store.update_episode_fields(sid, "ep_01", {"title": "雨夜初遇", "story_progress": "新进展"})
    got = store.get_episode(sid, "ep_01")
    check("字段更新生效", got["title"] == "雨夜初遇" and got["story_progress"] == "新进展")
    check("未更新字段保留", got["logline"] == "雨夜巷口的初遇")
    check("title 变更联动重命名", (store.story_dir(sid) / "02-episodes" / "ep_01-雨夜初遇.md").is_file()
          and not (store.story_dir(sid) / "02-episodes" / "ep_01-巷口初遇.md").exists())
    check("edited 置位", got["edited"] is True)

    store.upsert_episode(sid, {**ep, "episode_id": "ep_02", "title": "第二集"})
    check("list 排序", [e["episode_id"] for e in store.list_episodes(sid)] == ["ep_01", "ep_02"])
    check("delete", store.delete_episode(sid, "ep_02")
          and store.get_episode(sid, "ep_02") is None)

    print("== 5. entities（全局 ID） ==")
    e1 = store.upsert_entity(sid, "character", "林小雨", "短发女孩，眼神倔强", {"性格": "坚韧"})
    check("ID 分配 chr_001", e1["entity_id"] == "chr_001")
    check("row 键齐全（对齐 DB）", set(e1.keys()) == {
        "entity_id", "script_session_id", "entity_type", "name", "description", "meta",
        "lookbook_image_id", "lookbook_image_path", "created_at", "updated_at"})
    check("正文为 description", e1["description"] == "短发女孩，眼神倔强")
    check("meta 往返", e1["meta"] == {"性格": "坚韧"})

    # 跨 story 全局 ID 唯一
    sid2 = "bbbbbbbb-1111-2222-3333-444444444444"
    sm.create_session(sid2, workflow_type="script")
    store.ensure_story(sid2, title="另一部剧")
    e2 = store.upsert_entity(sid2, "character", "陈默", "沉默的店主")
    check("跨 story 不撞号", e2["entity_id"] == "chr_002")
    check("next_entity_id 全局", store.next_entity_id(sid, "character") == "chr_003")

    e1b = store.upsert_entity(sid, "character", "林小雨", "短发女孩，眼神倔强（修订）",
                              entity_id="chr_001")
    check("更新保留 ID", e1b["entity_id"] == "chr_001")
    check("更新正文", e1b["description"].endswith("（修订）"))
    scn = store.upsert_entity(sid, "scene", "巷口便利店", "深夜亮灯的便利店")
    check("scn 前缀", scn["entity_id"] == "scn_001")
    check("list 排序（type,id）", [(e["entity_type"], e["entity_id"]) for e in store.list_entities(sid)] == [
        ("character", "chr_001"), ("scene", "scn_001")])
    check("list 按类型过滤", [e["entity_id"] for e in store.list_entities(sid, "scene")] == ["scn_001"])
    check("set_entity_lookbook", store.set_entity_lookbook(sid, "chr_001", "lb_x", "static/images/a.png"))
    check("lookbook 引用读回", store.get_entity(sid, "chr_001")["lookbook_image_path"] == "static/images/a.png")
    check("delete_entity", store.delete_entity(sid, "scn_001") and store.get_entity(sid, "scn_001") is None)
    # 跨会话隔离：sid2 查 sid 的实体必须查不到（属主限定）
    check("跨会话 get_entity 为 None", store.get_entity(sid2, "chr_001") is None)
    check("跨会话 set_entity_lookbook 拒绝",
          store.set_entity_lookbook(sid2, "chr_001", "lb_y", "static/images/b.png") is False
          and store.get_entity(sid, "chr_001")["lookbook_image_id"] == "lb_x")

    print("== 6. storyboard ==")
    vsid = "cccccccc-9999-8888-7777-666666666666"
    segments = [
        {"index": 0, "title": "雨夜巷口全景", "outline": "雨夜，镜头从巷口拉进", "mode": "all_reference",
         "overlap": 0, "duration": 10, "prompt": "接续镜头的提示词文本", "reference_images": [
             {"image_id": "mat_1", "image_path": "static/images/x.png", "description": "参考图"}]},
        {"index": 1, "title": "便利店对峙", "outline": "两人隔柜对峙", "mode": "all_reference",
         "overlap": 1, "duration": 8, "prompt": "", "reference_images": []},
    ]
    sb = store.write_storyboard(sid, "ep_01", vsid, "# 分镜\n### 雨夜巷口全景\n- 内容", segments)
    check("result_data 形状（对齐旧 step_results）", set(sb.keys()) == {"mindmap", "edited", "segments", "segment_count"})
    check("segments 排序读回", [s["index"] for s in sb["segments"]] == [0, 1])
    seg0 = sb["segments"][0]
    check("frontmatter 配置读回", seg0["mode"] == "all_reference" and seg0["duration"] == 10 and seg0["overlap"] == 0)
    check("提示词正文读回", seg0["prompt"] == "接续镜头的提示词文本")
    check("参考图 frontmatter 读回", seg0["reference_images"][0]["image_id"] == "mat_1")
    check("空提示词读回空串", sb["segments"][1]["prompt"] == "")
    check("vs 目录确定性", store.storyboard_dir(sid, "ep_01", vsid).name == "vs-cccccccc")

    # 重新生成（清目录重写）
    store.write_storyboard(sid, "ep_01", vsid, "# 新导图", [
        {"index": 0, "title": "新分镜", "outline": "新内容", "duration": 5, "overlap": 0}])
    sb2 = store.read_storyboard(sid, "ep_01", vsid)
    check("重生成覆盖", sb2["segment_count"] == 1 and sb2["segments"][0]["title"] == "新分镜"
          and sb2["mindmap"] == "# 新导图")

    # 单镜更新
    store.update_segment_fields(sid, "ep_01", vsid, 0, {"mode": "first_frame", "overlap": 2, "prompt": "新提示词"})
    seg = store.read_segment(sid, "ep_01", vsid, 0)
    check("单镜字段更新", seg["mode"] == "first_frame" and seg["overlap"] == 2 and seg["prompt"] == "新提示词")
    check("未更新字段保留", seg["outline"] == "新内容" and seg["duration"] == 5)

    # 整体替换（导图编辑 reconcile 场景）
    store.replace_storyboard(sid, "ep_01", vsid, mindmap="# 编辑后导图", segments=[
        {"index": 0, "title": "新分镜", "outline": "新内容", "duration": 5, "overlap": 0, "prompt": "新提示词"},
        {"index": 1, "title": "追加分镜", "outline": "追加", "duration": 6, "overlap": 1},
    ], edited=True)
    sb3 = store.read_storyboard(sid, "ep_01", vsid)
    check("替换后计数", sb3["segment_count"] == 2 and sb3["edited"] is True)
    check("替换后 mindmap", sb3["mindmap"] == "# 编辑后导图")

    print("== 7. 级联清理 ==")
    counts = store.delete_story_content(sid)
    check("清空分集与实体", counts == {"episodes": 1, "entities": 1}
          and store.list_episodes(sid) == [] and store.list_entities(sid) == [])
    check("大纲与分镜保留", store.read_outline(sid) is not None
          and store.read_storyboard(sid, "ep_01", vsid) is not None)

    print("== 8. MAP 与 agent 入口 ==")
    store.upsert_entity(sid, "foreshadow", "雨伞的秘密", "一把黑伞的伏笔")
    map_text = (store.story_dir(sid) / "MAP.md").read_text(encoding="utf-8")
    check("MAP 含目录结构", "01-outline" in map_text and "02-episodes" in map_text)
    check("MAP 含实体清单", "fs_001-雨伞的秘密" in map_text)
    check("MAP 含边界规则", "边界规则" in map_text and "禁止读取工作区之外" in map_text)
    entry = store.agent_entry(sid)
    check("agent 入口可用", entry["available"] is True and entry["story_root"].endswith(store.story_dir(sid).name))
    check("MAP 摘要非空", "目录结构" in entry["map_summary"])

    print("== 9. 并发写 smoke ==")
    errors = []
    def writer(i: int):
        try:
            store.upsert_episode(sid, {**ep, "episode_id": f"ep_{i + 10:02d}", "title": f"并发集{i}"})
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    eps = [e["episode_id"] for e in store.list_episodes(sid)]
    check("并发 8 集全部落盘", len(eps) == 8 and not errors, f"errors={errors}")
    check("无 tmp 残留", not list((store.story_dir(sid)).rglob("*.tmp")))

    print("== 10. delete_story ==")
    check("删除整树", store.delete_story(sid) and store.story_dir(sid) is None)
    check("锚点清除", sm.get_session(sid)["workspace_path"] is None)
    try:
        store.rename_story(sid, "改名")
        check("删除后 rename 报错", False)
    except WorkspaceStoreError:
        check("删除后 rename 报错", True)

    print("== 11. 审查修复回归：ID 白名单 ==")
    sid3 = "cccccccc-1111-2222-3333-555555555555"
    sm.create_session(sid3, workflow_type="script")
    store.ensure_story(sid3)
    for bad_ep in ("*", "ep_01-x", "../ep_01", "ep_", "EP_01"):
        try:
            store.get_episode(sid3, bad_ep)
            check(f"非法 episode_id 拒绝: {bad_ep!r}", False)
        except WorkspaceStoreError:
            check(f"非法 episode_id 拒绝: {bad_ep!r}", True)
    for bad_ent in ("*", "chr_1", "xx_001", "chr_001-x"):
        try:
            store.get_entity(sid3, bad_ent)
            check(f"非法 entity_id 拒绝: {bad_ent!r}", False)
        except WorkspaceStoreError:
            check(f"非法 entity_id 拒绝: {bad_ent!r}", True)
    # 注入攻击复现路径：PUT episodes/* 不再可能误删（upsert/update/delete 均先校验）
    before = sorted(p.name for p in (store.story_dir(sid3) / "02-episodes").glob("*.md"))
    try:
        store.update_episode_fields(sid3, "*", {"title": "PWNED"})
        check("update_episode_fields('*') 拒绝", False)
    except WorkspaceStoreError:
        after = sorted(p.name for p in (store.story_dir(sid3) / "02-episodes").glob("*.md"))
        check("update_episode_fields('*') 拒绝且无文件变化", after == before)

    print("== 12. 审查修复回归：正文 ## 标题行转义往返 ==")
    tricky_chain = "第一阶段：发现线索\n## 内部小标题：伪装成定界符\n## 结尾摘要\nINJECTED_SPOOF\n第三阶段：收尾"
    tricky_ending = "真实结尾\n### 三级标题安全（不转义，不构成定界）\n最后一行"
    ep = store.upsert_episode(sid3, {
        "episode_id": "ep_01", "title": "转义测试", "logline": "梗概",
        "conflict_chain": tricky_chain, "causality_chain": "因果", "ending_summary": tricky_ending,
        "story_progress": "进展", "character_ids": ["chr_001"], "scene_ids": ["scn_001"],
        "clue_refs": [], "foreshadow_refs": [],
    })
    check("含 ## 行的矛盾链完整往返", ep["conflict_chain"] == tricky_chain)
    check("结尾摘要不被走私污染", ep["ending_summary"] == tricky_ending)
    # 更新另一字段后再读（读-改-写不固化截断）
    ep2 = store.update_episode_fields(sid3, "ep_01", {"logline": "新梗概"})
    check("读-改-写后仍完整", ep2["conflict_chain"] == tricky_chain and ep2["ending_summary"] == tricky_ending)
    seg_tricky = {"index": 0, "title": "分镜", "outline": "开头\n## 分镜提示词\n走私内容", "duration": 8,
                  "overlap": 0, "prompt": "提示词\n## 分镜大纲\n逆向走私"}
    store.write_storyboard(sid3, "ep_01", vsid := "dddddddd-0000-0000-0000-000000000000",
                           "# 导图", [seg_tricky])
    sb = store.read_storyboard(sid3, "ep_01", vsid)
    check("分镜 outline 完整往返", sb["segments"][0]["outline"] == seg_tricky["outline"])
    check("分镜 prompt 完整往返", sb["segments"][0]["prompt"] == seg_tricky["prompt"])
    raw = (store.storyboard_dir(sid3, "ep_01", vsid) / "seg_00-分镜.md").read_text(encoding="utf-8")
    check("文件内正文标题已转义", "\\## 分镜提示词" in raw and "\\## 分镜大纲" in raw)
    # 双射回归：原生字面 `\## `（前一轮方案的合法转义形态）往返不再静默漂移
    literal = "开头\n\\## 用户手打的字面反斜杠标题\n结尾"
    ep_lit = store.upsert_episode(sid3, {
        "episode_id": "ep_02", "title": "双射", "logline": "g", "conflict_chain": literal,
        "causality_chain": "c", "ending_summary": literal, "story_progress": "p",
        "character_ids": [], "scene_ids": [],
    })
    check("字面 \\## 行往返不漂移（双射）",
          ep_lit["conflict_chain"] == literal and ep_lit["ending_summary"] == literal)

    print("== 12b. 审查修复回归：分镜侧 episode_id 校验（路径穿越封堵） ==")
    victim = store.root.parent / "victim_outside"
    victim.mkdir(parents=True, exist_ok=True)
    (victim / "keep.txt").write_text("keep", encoding="utf-8")
    traversal = "../../../victim_outside"
    try:
        store.write_storyboard(sid3, traversal, vsid, "# x", [])
        check("write_storyboard 穿越 episode_id 拒绝", False)
    except WorkspaceStoreError:
        check("write_storyboard 穿越 episode_id 拒绝", True)
    check("树外目录未被 rmtree", (victim / "keep.txt").exists())
    for method, call in (
        ("read_storyboard", lambda: store.read_storyboard(sid3, traversal, vsid)),
        ("storyboard_dir", lambda: store.storyboard_dir(sid3, traversal, vsid)),
        ("episode_path", lambda: store.episode_path(sid3, traversal)),
        ("segment_path", lambda: store.segment_path(sid3, traversal, vsid, 0)),
        ("replace_storyboard", lambda: store.replace_storyboard(sid3, traversal, vsid, mindmap="# x")),
        ("read_segment", lambda: store.read_segment(sid3, traversal, vsid, 0)),
    ):
        try:
            call()
            check(f"{method} 穿越 episode_id 拒绝", False)
        except WorkspaceStoreError:
            check(f"{method} 穿越 episode_id 拒绝", True)
    # 正则加固：尾换行与全角数字拒绝
    for sneaky in ("ep_01\n", "ep_０１"):
        try:
            store.get_episode(sid3, sneaky)
            check(f"加固正则拒绝: {sneaky!r}", False)
        except WorkspaceStoreError:
            check(f"加固正则拒绝: {sneaky!r}", True)
    # 非法 entity_id 不再产生 ensure_story 目录副作用
    sid_ghost = "eeeeeeee-0000-0000-0000-000000000000"
    sm.create_session(sid_ghost, workflow_type="script")
    try:
        store.upsert_entity(sid_ghost, "character", "幽灵", "x", entity_id="*")
        check("非法 entity_id 校验先于建目录", False)
    except WorkspaceStoreError:
        check("非法 entity_id 校验先于建目录",
              store.story_dir(sid_ghost) is None or not (store.story_dir(sid_ghost) / "03-entities").glob("*-*.md"))
    import shutil as _shutil
    _shutil.rmtree(victim, ignore_errors=True)

    print("== 13. 审查修复回归：跨会话并发 ID 分配不撞号 ==")
    ids_lock_free: list[str] = []
    errors2 = []
    def creator(sess: str, n: int):
        try:
            for _ in range(n):
                e = store.upsert_entity(sess, "foreshadow", f"并发伏笔{sess[:4]}")
                ids_lock_free.append(e["entity_id"])
        except Exception as e:  # noqa: BLE001
            errors2.append(e)
    t1 = threading.Thread(target=creator, args=(sid3, 6))
    t2 = threading.Thread(target=creator, args=(sid2, 6))
    t1.start(); t2.start(); t1.join(); t2.join()
    check("并发 12 个实体 ID 全局唯一", len(set(ids_lock_free)) == 12 and not errors2,
          f"errors={errors2[:2]}")
    check("ID 连续无空洞", sorted(ids_lock_free) == sorted(set(ids_lock_free)))


if __name__ == "__main__":
    main()
