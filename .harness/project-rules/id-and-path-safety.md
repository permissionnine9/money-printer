---
name: id-and-path-safety
摘要: episode_id/entity_id 拼入 glob/文件路径前必须过白名单正则校验，防元字符注入与路径穿越；文件名一律 sanitize_name 净化；非法 ID 不留目录副作用。
tags: [安全, 门禁, ID校验, 路径穿越, workspace-store]
---

# ID 命名与路径安全门禁

**类别:** 门禁
**最后更新:** 2026-09-21

## 原因

API 路径参数会被直接拼进 glob 模式与文件路径（backend/core/persistence/workspace_store.py L40-41 代码注释动机）：不先做格式校验，元字符注入与路径穿越即不可防——

- **glob 元字符注入**：`episode_id="*"` 会令 `glob("*-*.md")` 误匹配并触发 `_replace_doc_file` 清空分集。
- **路径穿越 + 目录删除放大**：`episode_id="../../../victim_outside"` 若触达 `write_storyboard`（内部 `shutil.rmtree` 清目录，L736-738），会波及工作区树外文件。
- **正则锚点与字符集陷阱**：`$` 会放行尾换行 `"ep_01\n"`，必须 `\Z` 绝对锚定；缺省语义会放行全角数字 `"ep_０１"`，必须 `[0-9]` 显式 ASCII + `re.ASCII`。
- **LLM 自由文本定界符冲突**：正文字段值中 LLM 自由文本可能含行首 `## `，与 `_SECTION_RE`（L90）的小节定界符冲突导致字段走私/截断，需转义双射。
- **文件名不可信**：标题/名称来自用户或 LLM，必须经 `sanitize_name` 净化后才能进入文件名。

根本不变式：**所有 storyboard 系方法在持锁/建目录/删除目录（rmtree）之前先做 `_require_episode_id`**——这是穿越攻击不可达的根本原因。

## 适用范围

> **行号为 2026-09-19 快照，可能随版本漂移，以方法名为准**（本次修订不逐一重对标 L407/L517 等行号）。

- backend/core/persistence/workspace_store.py —— `WorkspaceStore` 全部公开方法：任何会把 `episode_id`/`entity_id`/`entity_type`/`title`/`name` 拼进 glob 或文件路径的新增方法，首行必须调用 `_require_episode_id` / `_require_entity_id`。**后续新增方法均已遵守同一门禁**（均含 ID 校验/净化路径）：`read_story_title` / `set_story_title`（剧名读写）、`entity_references` / `delete_entity_unreferenced`（实体引用检查与安全删除：仅无引用实体可删）、`delete_last_episode`（删除最后一集）。
- API/MCP 层：`EPISODE_ID_PATTERN` / `ENTITY_ID_PATTERN` 为 API schema 共享字符串（L47-48，注释 L45-46 说明 pydantic/FastAPI rust regex 引擎语义等价）；实际消费方：backend/schemas/script.py、backend/schemas/steps.py 的 Field(pattern=...)，backend/api/v1/script_sessions.py L48-49 的 `Path(pattern=...)` 路径参数。`WorkspaceStoreError` 继承 `ValueError`（L133-134），以复用 API/MCP 层既有捕获。
- 净化与配置依赖：backend/core/utils/image_store.py 的 `sanitize_name`（L21-27）；backend/core/config.py L18-19 定义 `WORKSPACE_DIR`（项目根 workspace/，导入时 L24 `mkdir(parents=True, exist_ok=True)` 确保存在）；`WorkspaceStore.__init__`（workspace_store.py L186-197）缺省取该值并再次 mkdir。
- 运行链（路径来源）：`session_manager` 缺省时 `_anchor_sm` 延迟导入 `backend.deps.get_script_session_manager` 单例（避免循环导入）；锚点回写——`ensure_story`/`rename_story` 调 `session_manager.set_workspace_path(sid, name)`，`delete_story` 置 None（L696）。
- 回归防线：tests/manual/ 现为 **6 个文件**（新增 test_agent_run_queue.py / test_lookbook_library.py / test_narrative_prompt_chain.py）；test_workspace_store.py（346 行，直接 python 运行的 smoke 断言集，非 pytest）仍为本门禁主防线；test_phase1_data.py 已改为**文件化架构下测试**（实体/分集读写走 WorkspaceStore，ScriptManager 仅剩任务状态机表）。
- 迁移永不 DROP 表：backend/scripts/migrate_db_to_workspace.py（L283/L321/L338 注释与实现均为「备份 + DELETE 行」，永不 DROP）；细则由 project-rules/workspace-authoritative-storage.md 约束。ScriptManager 的 episodes/script_entities **影子表已退役**（DDL 与读写删除），迁移脚本仍用原生 SQL 只读对账 —— 本门禁（WorkspaceStore 的 ID 校验与路径净化）不受影响。

## 示例

✅ **正确做法:**

**1. ID 白名单正则（backend/core/persistence/workspace_store.py L43-48）**

```python
# API schema 共享字符串（注释说明 pydantic/FastAPI rust regex 引擎语义等价）
EPISODE_ID_PATTERN = r"^ep_[0-9]{2,}$"
ENTITY_ID_PATTERN = r"^(chr|scn|clu|fs)_[0-9]{3,}$"

# 代码侧编译：\Z 绝对锚定（拒绝尾换行）+ [0-9] 显式 ASCII + re.ASCII（拒绝全角数字）
_EPISODE_ID_RE = re.compile(r"^ep_[0-9]{2,}\Z", re.ASCII)                # ep_ + 至少 2 位数字
_ENTITY_ID_RE = re.compile(r"^(chr|scn|clu|fs)_[0-9]{3,}\Z", re.ASCII)   # 至少 3 位数字
```

实体类型前缀映射 `ENTITY_ID_PREFIXES = {character: chr, scene: scn, clue: clu, foreshadow: fs}`（L62-67）；`entity_type` 不在其中时抛 `ValueError`（L430-431）。

**2. 校验函数与错误类型**

- `WorkspaceStoreError`（L133-134）继承 `ValueError`，注释说明含非法 ID 校验并复用 API/MCP 层既有捕获。
- `_require_episode_id`（L106-109）/ `_require_entity_id`（L112-115）：match 失败抛 `WorkspaceStoreError`，消息含原始 `repr` 值（实体侧消息为「应为 chr_001/scn_001 形式」），通过则原样返回。

**3. 每个可能拼路径的公开方法首行校验**

| 侧 | 已覆盖方法（行号） |
|----|----|
| entity（`_require_entity_id`） | `_find_entity_file`(L407)、`delete_entity`(L517)、`set_entity_lookbook`(L530)、`upsert_entity`(L433) |
| episode（`_require_episode_id`） | `upsert_episode`(L547)、`get_episode`(L632)、`delete_episode`(L650)、`storyboard_dir`(L704)、`episode_path`(L710)、`segment_path`(L720)、`write_storyboard`(L732)、`read_storyboard`(L790)、`replace_storyboard`(L817)、`update_segment_fields`(L847)、`read_segment`(L871) |
| 例外 | `update_episode_fields`(L571) 未直接调用 `_require_episode_id`，但它先调 `get_episode`（L573，内部校验），非法 ID 在读取阶段即被拒 |

**4. 校验先于目录副作用**

`upsert_entity` L432-433：`if entity_id: _require_entity_id(entity_id)` 在 L435 `ensure_story(script_session_id)` 之前（注释「非法 ID 不留目录副作用」）；`upsert_episode` L547 同样先于 L549 `ensure_story`；`storyboard_dir` L704 先校验再 `ensure_story`。分镜目录 `storyboard_dir` L702-706 拼接 `story/04-storyboards/{episode_id}/vs-{video_session_id[:8]}` 时，`episode_id` 已过白名单后才拼接。

**5. 文件名与路径净化**

- story 目录名：`ensure_story`(L240)/`rename_story`(L255)/`write_outline`(L337) 均为 `f"{sanitize_name(title or '未命名剧本', max_len=40)}-{script_session_id[:8]}"`，id 前 8 位后缀保证唯一。
- `_doc_name`(L178-180)：文件名 = `f"{doc_id}-{sanitize_name(name, max_len=30, fallback='untitled')}.md"`，id 前缀保证排序与 glob 精确匹配。
- `sanitize_name`（backend/core/utils/image_store.py L21-27）：去非法字符（`_INVALID_CHARS = [/\\:*?"<>|\x00-\x1f]`，L18）、空白转下划线、`strip("._")`、限长、空值兜底 fallback。
- `story_dir` 定位（L216-229）：`sessions.workspace_path` 锚点优先（`path = self.root / anchor`，`is_dir` 校验，失效则 warning 回退），否则 glob `f"*-{script_session_id[:8]}"` 兜底；不存在返回 None（不抛错）。

**6. markdown 正文 `## ` 标题行转义双射（L90-103）**

- 写入转义：`_ESCAPE_HEADING_RE = re.compile(r"^(\\*)(#{2,}\s)", re.MULTILINE)`，`_escape_headings` 在行首标题（含已被转义的）前再补一个 `\`；应用于 `_render_episode_content`（L118-122，`EPISODE_SECTIONS` 五节：梗概/矛盾链/因果链/结尾摘要/节点进展）与 `_render_segment_content`（L125-130，分镜大纲/分镜提示词两节）。
- 读取还原：`_UNESCAPE_HEADING_RE = re.compile(r"^(\\+)(#{2,}\s)", re.MULTILINE)`，`_unescape_headings` 将 N 个反斜杠减为 N-1 个；`_episode_from_doc`（L612-616）与 `_segment_from_doc`（L773,778）对对应小节还原。
- 双射含义：按已有反斜杠数量计数，原文 `"\## x"` 写为 `"\\## x"`，读取还原为 `"\## x"`——原生字面反斜杠形态不会误解码/静默漂移。转义匹配 `#{2,}`，所有 ≥2 级标题行（含 `###`）均会被补 `\`（保守冗余，往返无损）；小节定界 `_SECTION_RE` 仅认 `^##\s`，`###` 更深层级不构成定界。
- 定界符：`_SECTION_RE = re.compile(r"^##\s+(.*?)\s*$")`（L90）。

**7. 并发与原子性**

- 原子写：`_static_write`（L304-308）写 `path.name + ".tmp"` 后 `os.replace(tmp, path)`；测试第 215 行断言无 `*.tmp` 残留。
- 实体 ID 全局锁：`_ENTITY_ID_LOCK = threading.Lock()`（L60，进程级，因 ID 跨 story 全局分配、glob MAX+1 非原子）；新建路径 L461 在 `with _ENTITY_ID_LOCK` + per-story RLock 内完成「分配 ID + 落盘」。
- per-story 可重入锁：`_story_lock`（L208-214），`self._locks` dict + `_locks_guard` 保护；`ensure_story` 双检防并发建目录（L236-239）。

**8. 攻击面回归断言（tests/manual/test_workspace_store.py）**

- glob 元字符：`get_episode`/`get_entity`/`update_episode_fields` 对 `"*"` 抛 `WorkspaceStoreError`；`update_episode_fields("*", ...)` 被拒后 `02-episodes` 目录文件列表不变。
- ID 变体拒绝：`"ep_01-x"`、`"../ep_01"`、`"ep_"`、`"EP_01"`；`"chr_1"`、`"xx_001"`、`"chr_001-x"`。
- 路径穿越封堵（L284-307）：`episode_id="../../../victim_outside"` 时 7 个方法（read_storyboard/storyboard_dir/episode_path/segment_path/replace_storyboard/read_segment/write_storyboard）均抛 `WorkspaceStoreError`，树外 `victim/keep.txt` 未被删除。
- 边界强化：`"ep_01\n"`（尾换行）与 `"ep_０１"`（全角数字）均被拒绝；非法 `entity_id="*"` 的 `upsert_entity` 在 `ensure_story` 建目录前被拒（sid_ghost 无 `03-entities` 实体文件）。
- 转义往返（L251-282）：矛盾链含 `## 内部小标题`/`## 结尾摘要` 走私行完整往返不截断；分镜 outline/prompt 互相走私定界符也完整往返；文件原文含 `"\\## 分镜提示词"`；字面 `"\\## "` 双射往返不漂移；`update_episode_fields` 读-改-写后仍完整。
- 并发：第 203-215 行 8 线程并发 `upsert_episode` 全部落盘；第 327-342 行双会话并发 `upsert_entity` 12 个 ID 全局唯一且连续无空洞。
- 测试入口：`main()` 用 `tempfile.mkdtemp` + `SessionManager(db_path=..., steps=SCRIPT_STEPS)` 注入临时目录构造 `WorkspaceStore(workspace_dir, session_manager)`，覆盖 14 组场景（编号 1-13，另含 12b 路径穿越封堵）；退出码 `1 if FAIL else 0`。

❌ **错误做法:**

- **跳过白名单校验直接拼 glob/路径**：`episode_id="*"` 令 `glob("*-*.md")` 误匹配并触发 `_replace_doc_file` 清空分集；`episode_id="../../../victim_outside"` 触达 `write_storyboard` 内部 `shutil.rmtree`（L736-738），树外 `victim/keep.txt` 会被删除。
- **用 `$` 代替 `\Z`**：尾换行 `"ep_01\n"` 会被放行。
- **用 `\d` 或缺 `re.ASCII`**：全角数字 `"ep_０１"` 会被放行。
- **先 `ensure_story` 建目录再校验 ID**：非法 ID 留下目录副作用（sid_ghost 场景正是靠「校验先于建目录」保证无 `03-entities` 实体文件）。
- **持锁/建目录/rmtree 之前不校验**：破坏「锁与校验次序不变式」，路径穿越将可达。
- **直接用用户/LLM 文本做文件名**（不经 `sanitize_name`）：`/`、`\`、`:`、`*`、`?`、`"`、`<`、`>`、`|` 与控制字符 `\x00-\x1f` 进入路径。
- **正文行首 `## ` 不转义直接落盘**：与 `_SECTION_RE` 定界符冲突，字段走私/截断（转义往返断言将失败）。
- **非原子写**（不经 `.tmp` + `os.replace`）：残留 `*.tmp`（测试第 215 行断言禁止）。
- **新增拼路径的公开方法不校验也不经由已校验路径**：如既不调用 `_require_episode_id`/`_require_entity_id`，也不像 `update_episode_fields` 那样先调 `get_episode`（读取阶段即被拒）。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修正 — 测试文件行数 343→346、场景组 13→14（含 12b）；修正 `###` 转义语义（`#{2,}` 含 `###` 均转义，仅 `^##\s` 构成定界）；`upsert_entity` 校验行号 L434→L432-433（ensure_story 在 L435）；`WORKSPACE_DIR` 定义位置改为 config.py L18-19（`__init__` L186-197 为缺省取值处）；「迁移永不 DROP 表」由待补充占位改为已验证引用（migrate_db_to_workspace.py L283/L321/L338）；补充 PATTERN 实际消费方文件；「升级 ID 拒绝」措辞改「ID 变体拒绝」 |
| 2026-09-21 | 迭代修订 — 适用范围追加 WorkspaceStore 新方法（read_story_title/set_story_title、entity_references/delete_entity_unreferenced（仅无引用实体可删）、delete_last_episode，均含 ID 校验/净化路径）；开头注明「行号为 2026-09-19 快照，以方法名为准」（L407/L517 等已漂移，不逐一重对标）；回归防线更新为 tests/manual 共 6 个文件（新增 test_agent_run_queue.py / test_lookbook_library.py / test_narrative_prompt_chain.py，test_phase1_data.py 已改文件化架构下测试）；补 ScriptManager episodes/script_entities 影子表退役说明（迁移脚本仍用原生 SQL 只读对账，本门禁不受影响） |
