---
name: 文件上传与会话资产管理
摘要: 通用图片上传线（POST /api/v1/uploads/image 等，uuid 命名落盘 static/uploads 不进库，save_upload 内联于 uploads.py）；原 /api/v1/assets 会话资产管理路由（含音频登记）已于 2026-09-21 整体删除，_upload.py 公共落盘模块随之移除。
tags: 文件上传, 后端API, 资产管理, SQLite, 静态文件
---

# 文件上传与会话资产管理

**状态:** 已完成（assets 管理线已删除）
**最后更新:** 2026-09-21

## 功能概述

当前仅存一条上传链路：

1. **通用图片上传**（`/api/v1/uploads`，POST `/api/v1/uploads/image` 等）：匿名图片落盘，返回相对路径与 `/static/uploads/...` 访问 URL，不登记数据库。前端消费方是「AI 生成素材图」弹窗上传自定义参考图（`MaterialGenerateModal`）。

**已删除的链路（2026-09-21）**：

- `/api/v1/assets` 会话素材管理台（GET 列表 / POST 上传登记 / DELETE 删记录，103 行整体删除）——**会话资产（audio）管理能力随路由移除**；
- 公共落盘模块 `backend/api/v1/_upload.py`（55 行）删除，`save_upload` + `UPLOAD_ROOT` + `MAX_UPLOAD_SIZE` **内联进 uploads.py**（其头部注明「assets 路由已删除」）；
- 前端 `client.ts` 的 assetApi（list/upload/remove）同步删除。

整体数据流（现状）：前端 `uploadApi`（axios，`/api/v1`）→ `backend/api/v1/uploads.py`（内联版 save_upload，uuid 命名落盘 `static/uploads`）→ 经 `main.py` 的 `/static` 挂载对外访问。

## 核心代码路径

- `backend/api/v1/uploads.py` — 通用图片上传路由（挂载 `/api/v1/uploads`）：POST `/api/v1/uploads/image` 等端点，MIME 前缀校验 + 扩展名白名单落盘，返回 `file_path` 与 `url`，不进库；原 `_upload.py` 的 save_upload/UPLOAD_ROOT/MAX_UPLOAD_SIZE 内联于此（头部注明「assets 路由已删除」）
- `backend/main.py` — 路由注册与静态目录挂载（`app.mount("/static", ...)`）；现挂载 8 个 router：sessions / steps / uploads / models / prompts / settings / script_sessions / agent_runs（assets 已不在列）
- `backend/core/persistence/session_manager.py` — 持久层遗留：`session_assets` 表建表（第 84 行起）与 `add_asset`/`list_assets`/`get_asset`/`delete_asset`（第 630-711 行）；`delete_session` 级联删除资产记录（第 614 行）——HTTP 管理入口移除后仅剩内部调用可能
- `backend/deps.py` — 依赖注入：`get_session_manager`（lru_cache 单例）等
- `frontend/src/api/client.ts` — 前端 API client：`uploadApi`（uploadImage）；assetApi（list/upload/remove）已删除
- `frontend/src/types/index.ts` — TS 类型 `SessionAsset`（历史遗留类型）
- `frontend/src/components/workflow/material/MaterialGenerateModal.tsx` — 前端消费方：AI 生成素材图弹窗，`handleUpload` 调 `uploadApi.uploadImage` 上传自定义参考图，路径并入 `reference_paths` 提交

已删除文件（保留记录便于追溯）：`backend/api/v1/assets.py`（103 行，会话素材管理台 CRUD）、`backend/api/v1/_upload.py`（55 行，公共落盘工具）。

## 关键逻辑说明

### 通用图片上传（backend/api/v1/uploads.py，挂载前缀 /api/v1/uploads）

| 路由 | 处理函数 | 行为 |
|------|---------|------|
| POST /uploads/image | upload_image | content_type 非空且以 `image/` 开头（否则 400 `只能上传图片文件`）→ save_upload 落盘（default_ext=".png"、allowed_exts=IMAGE_EXTS）→ 返回 `{success, message:'文件上传成功', file_path:"static/uploads/<uuid>.<ext>", url:"/static/uploads/<uuid>.<ext>"}` |

- `IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}`。
- 内联落盘逻辑（原 _upload.py 的 save_upload，语义不变）：扩展名取原始文件名（lower）白名单校验——注释明确「content_type 可被客户端伪造，落盘前以扩展名为准」；落盘文件名 `uuid4 + 扩展名`（无扩展名用 default_ext 兜底）；目标目录 `mkdir(parents=True, exist_ok=True)`；1MB 分块写入并累计，超 `MAX_UPLOAD_SIZE`（20MB）抛 400（`文件超过大小上限 20MB`）；任何异常 `unlink` 清理半成品文件。
- 不写数据库、不关联会话；文件经 `main.py` 的 `/static` 挂载对外可访问。

### main.py 路由注册

- 现挂载 8 个 router：sessions / steps / uploads / models / prompts / settings / script_sessions / agent_runs（assets 已不在挂载列表）。
- 静态目录：`app.mount("/static", ...)`，static/uploads 下的文件经此外露。

### 持久层遗留（session_manager.py）

- 表 `session_assets`：`asset_id TEXT PRIMARY KEY`(uuid4)、`session_id`、`asset_type`、`name`、`file_path`、`meta`、`created_at`；无 FOREIGN KEY 约束（与 sessions 仅逻辑关联）。
- `add_asset`/`list_assets`/`get_asset`/`delete_asset` 方法仍在；`delete_session` 同一事务内先删 `step_results` → 再删 `session_assets` → 最后删 `sessions`（级联清理资产记录，磁盘文件保留）。
- assets HTTP 路由删除后，`session_assets` **不再有登记入口**，仅作为历史数据与内部调用残留存在。

### 前端（frontend/src/api/client.ts + MaterialGenerateModal.tsx）

- `uploadApi.uploadImage(file)`：FormData POST `/uploads/image`，返回 `{file_path, url}`。
- `assetApi`（list/upload/remove）已从 client.ts 删除，前端无调用方。
- `MaterialGenerateModal`（AI 生成素材图弹窗，antd Upload）：`handleUpload` 调 `uploadApi.uploadImage`，成功后把 `file_path` 追加到 `uploadPaths`；提交时 `uploadPaths` 作为 `reference_paths` 传 `stepApi.generateSegmentMaterial`（与 @ 素材引用、素材池选择并列的第三种参考图来源）——此链路不变。

## 依赖与复用关系

- 依赖: FastAPI（UploadFile/File/HTTPException）、StaticFiles（`/static` 挂载）、SQLite（data/sessions.db，session_assets 表遗留）；前端 axios（client.ts，baseURL `/api/v1`）、antd（MaterialGenerateModal 的 Upload/message）
- 被依赖: `frontend/src/components/workflow/material/MaterialGenerateModal.tsx`（uploadApi 参考图上传）
- 可复用组件: 内联于 uploads.py 的落盘逻辑（白名单/uuid 命名/分块限流/异常清理）——新增上传路由时可参照该模式抽取

## 注意事项

- **assets 管理线已删除**：`/api/v1/assets` CRUD、`backend/api/v1/_upload.py`、前端 assetApi 均于 2026-09-21 移除；历史「会话音频资产 → ComfyUI 参考音频」消费链（原 workflow_v2 `list_assets(asset_type="audio")` → comfyui_service `generate_full_video(audio_assets=...)`）随管理/登记能力一并失效，不再有上传登记入口。
- **删除不清理磁盘**（历史行为沿用）：session_assets 记录的删除/级联删除均只删记录不删 `static/uploads` 文件，需人工清理。
- **上限 20MB**：`MAX_UPLOAD_SIZE`（20MB）对上传线生效，大文件可能超限。
- **file_path 存本地相对路径**：uploads.py 拼接 `static/uploads/{name}` 形式的相对路径（相对后端工作目录），消费端按本地文件路径读取。
- **上传路由无鉴权**：上传路由无登录态/鉴权依赖，仅靠 CORS 白名单（localhost:5173/3000）限制浏览器来源。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析自动生成（当时含 /api/v1/assets 会话资产管理线与 _upload.py 公共落盘模块） |
| 2026-09-21 | assets 路由整体删除（103 行，会话素材管理台 CRUD 移除，音频资产管理能力下线）；_upload.py（55 行）删除、save_upload/UPLOAD_ROOT/MAX_UPLOAD_SIZE 内联进 uploads.py（头部注明「assets 路由已删除」）；main.py 收敛为 8 个 router（sessions/steps/uploads/models/prompts/settings/script_sessions/agent_runs）；前端 assetApi 删除 |