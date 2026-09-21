---
name: lookbook-library
摘要: 跨剧本核心素材图素材库 — 复用任意剧本会话已完成的核心素材图，复制导入绑定到当前实体，含孤儿过滤/溯源/回滚/级联保留。
tags: [素材库, lookbook, 核心素材图, 跨会话复用, 导入]
---

# 核心素材图素材库（lookbook library）

**状态:** 已实现（2026-09-21）

## 解决什么问题

核心素材图（原「定妆照」）生成耗时费钱；新剧本中相同类型实体（如常见场景/人物原型）往往与历史剧本高度重复。素材库允许**复用任意历史剧本会话已完成的核心素材图**——复制导入并绑定到当前实体，避免重复生成。

## 核心代码路径

- `backend/core/services/lookbook_library_service.py` — 领域服务：`list_lookbook_library`（:16-57）/ `import_lookbook_from_library`（:60-99）
- `backend/api/v1/script_sessions.py` — API 层：GET `/{sid}/lookbook/library`（:379-386）、POST `/{sid}/lookbook/import`（:388-396）
- `backend/schemas/script.py` — `LookbookImportRequest`（:88-90）
- `backend/core/persistence/script_manager.py` — 持久层：`list_completed_lookbooks`（:125-134，全局 completed 且 image_path 非空）、`insert_lookbook`（:60-79，新增 image_path/meta 参数）
- `backend/core/services/regeneration.py` — 级联保留：`cascade_regenerate` 调 `delete_script_data(keep_completed_lookbooks=True)`
- `frontend/src/components/script/LookbookLibraryModal.tsx` — 素材库选择弹窗（:22-123）
- `frontend/src/components/script/StepLookbook.tsx` — 入口：「从素材库选择」按钮（:268/:297）、`handleImported`（:178-181）
- `tests/manual/test_lookbook_library.py` — 手工测试（218 行，覆盖保留语义/跨会话过滤/HTTP 层）

## 逻辑流程

### 查询侧（list_lookbook_library）

1. `list_sessions(workflow_type="script")` 取存活会话集合，**过滤孤儿行**——孤儿来源：通用删除端点不清理 lookbook 表 + script-sessions 删除中途失败（lookbook_library_service.py 文件头注释记录该取舍）。
2. `list_completed_lookbooks` 取**全局** completed 且 image_path 非空的素材行，按会话分组。
3. 排序：当前会话组排第一（key="current"），其余按组内最新素材 created_at 倒序。
4. 素材项含 entity_id / entity_name / entity_exists（源实体已删的素材标注，前端显示「实体已失效」）。

### 导入侧（import_lookbook_from_library）

1. 校验：源行 completed 且有 image_path、目标实体存在。
2. `insert_lookbook` **复制为新行**——引用同一远程 URL（无额外存储开销），meta 写 `imported_from{image_id, script_session_id, entity_id}` 溯源。
3. `store.set_entity_lookbook` 回写目标实体 frontmatter 锚点。
4. 异常回滚：set_entity_lookbook 抛异常时 `delete_lookbook` 回滚复制行后 re-raise；返回 falsy（目标实体被并发删除）时回滚并抛 404 WorkflowError。

### 级联保留（cascade_regenerate）

- 大纲等上游重生成时调 `delete_script_data(keep_completed_lookbooks=True)`：仅删未完成/无图行，**保留已完成有图行**作为历史素材（素材库价值的来源）。
- 分集素材图（episode_material_images）两种模式都全删——与集号强绑定，不做保留。

## 关键设计

- **复制而非引用**：导入后新行与源行独立演化（后续重生成/删除互不影响）。
- **死会话素材不进库**：以存活会话集合过滤，避免悬空数据进入素材库。
- **前端复用 MaterialGrid**：分组展示、单选绑定（LookbookLibraryModal 单选，再点取消）。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-21 | 初始创建 — 随「核心素材图+素材库」功能落地；tests/manual/test_lookbook_library.py（218 行）覆盖保留语义/跨会话过滤/HTTP 层 |