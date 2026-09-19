---
name: 文件上传与会话资产管理
摘要: 两条上传线：/api/v1/uploads/image 通用图片落盘（uuid 命名不进库）与 /api/v1/assets 会话资产登记（session_assets 表，音频供 ComfyUI 参考音频消费），共用 _upload.save_upload 分块落盘与扩展名白名单。
tags: 文件上传, 后端API, 资产管理, SQLite, 静态文件
---

# 文件上传与会话资产管理

**状态:** 已完成
**最后更新:** 2026-09-19

## 功能概述

系统有两条独立的上传链路，共用同一份落盘工具（`backend/api/v1/_upload.py` 的 `save_upload`）：

1. **通用图片上传**（`/api/v1/uploads/image`）：匿名图片落盘，返回相对路径与 `/static/uploads/...` 访问 URL，不登记数据库。当前唯一前端消费方是「AI 生成素材图」弹窗上传自定义参考图（`MaterialGenerateModal`）。
2. **会话资产管理**（`/api/v1/assets`）：把音频/图片文件落盘并登记到 SQLite `session_assets` 表（按会话隔离），支持列表/上传/删除记录。视频生成工作流（步骤7 ComfyUI 整段生成）会读取会话音频资产作为参考音频上传到 ComfyUI。

整体数据流：前端 `uploadApi`/`assetApi`（axios，`/api/v1`）→ `backend/api/v1/uploads.py` / `backend/api/v1/assets.py` → `save_upload`（uuid 命名落盘 `static/uploads`）→（仅资产线）`SessionManager.add_asset` 登记表 → 视频工作流 `workflow_v2` 经 `list_assets(asset_type="audio")` 消费。

## 核心代码路径

- `backend/api/v1/_upload.py` — 公共落盘逻辑：`UPLOAD_ROOT = static/uploads`、`MAX_UPLOAD_SIZE = 20MB`、`save_upload()`（扩展名白名单 + uuid 命名 + 1MB 分块写 + 超限/异常清理）
- `backend/api/v1/uploads.py` — 通用图片上传路由：POST `/api/v1/uploads/image`，MIME 前缀校验 + 扩展名白名单落盘，返回 `file_path` 与 `url`，不进库
- `backend/api/v1/assets.py` — 会话资产管理路由（挂载 `/api/v1/assets`）：GET 列表 / POST 上传登记 / DELETE 删记录，MIME 白名单 + 扩展名回退双重校验
- `backend/core/persistence/session_manager.py` — 持久层：`session_assets` 表建表（第 84 行起）与 `add_asset`/`list_assets`/`get_asset`/`delete_asset`（第 630-711 行）；`delete_session` 级联删除资产记录（第 614 行）
- `backend/core/agents/workflow_v2.py` — 消费方：步骤7 视频生成前 `list_assets(session_id, asset_type="audio")` 收集参考音频（第 225 行）
- `backend/core/services/comfyui_service.py` — 消费方：`generate_full_video` 把音频资产文件上传 ComfyUI（第 458-464 行）并按 `audioMode`（默认 `reference`）定义素材（第 126-136 行）
- `backend/main.py` — 路由注册（第 79-80 行：uploads/assets 前缀）与静态目录挂载（第 65 行：`app.mount("/static", ...)`）
- `backend/deps.py` — 依赖注入：`get_session_manager`（lru_cache 单例）与 `load_video_session`（会话不存在抛 404）
- `frontend/src/api/client.ts` — 前端 API client：`assetApi`（第 203 行起，list/upload/remove）与 `uploadApi`（第 320 行起，uploadImage）
- `frontend/src/types/index.ts` — TS 类型 `SessionAsset`（第 223 行起）
- `frontend/src/components/workflow/material/MaterialGenerateModal.tsx` — 前端消费方：AI 生成素材图弹窗，`handleUpload` 调 `uploadApi.uploadImage` 上传自定义参考图（第 84 行），路径并入 `reference_paths` 提交

## 关键逻辑说明

### 公共落盘（backend/api/v1/_upload.py）

- `save_upload(file, target_dir, *, default_ext="", allowed_exts=None, max_size=20MB) -> Path`
- 扩展名取自原始文件名（lower），`allowed_exts` 非空时不在白名单即 400（`不允许的文件类型: xxx`）——注释明确「content_type 可被客户端伪造，落盘前以扩展名为准」。
- 落盘文件名 `uuid4 + 扩展名`；无扩展名时用 `default_ext` 兜底；目标目录 `mkdir(parents=True, exist_ok=True)`。
- 1MB 分块写入并累计，超 `max_size` 抛 400（`文件超过大小上限 20MB`）；任何异常 `unlink` 清理半成品文件；`finally` 关闭底层文件句柄。

### 通用图片上传（backend/api/v1/uploads.py，挂载前缀 /api/v1/uploads）

| 路由 | 处理函数 | 行为 |
|------|---------|------|
| POST /uploads/image | upload_image | content_type 非空且以 `image/` 开头（否则 400 `只能上传图片文件`）→ `save_upload(UPLOAD_ROOT, default_ext=".png", allowed_exts=IMAGE_EXTS)` → 返回 `{success, message:'文件上传成功', file_path:"static/uploads/<uuid>.<ext>", url:"/static/uploads/<uuid>.<ext>"}` |

- `IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}`。
- 不写数据库、不关联会话；文件经 `main.py` 的 `/static` 挂载对外可访问。

### 会话资产管理（backend/api/v1/assets.py，挂载前缀 /api/v1/assets）

三条路由均 `Depends(load_video_session)`（会话不存在 404 `会话 {session_id} 不存在`）：

| 路由 | 处理函数 | 行为 |
|------|---------|------|
| GET /assets/{session_id}?asset_type= | list_assets | 可选过滤 `audio`/`image`，非法值 400（`asset_type 仅支持 audio 或 image`）；返回 `{success, assets}`（created_at 倒序） |
| POST /assets/{session_id}/upload?asset_type= | upload_asset | `asset_type` 限 `audio`/`image`（400）；MIME 白名单 + 扩展名回退双重校验；音频落 `static/uploads/audio`、图片落 `static/uploads`；`add_asset` 登记后返回 `{success, message:'文件上传成功', asset}` |
| DELETE /assets/{session_id}/{asset_id} | delete_asset | `get_asset` 不存在或 `session_id` 不匹配 → 404（`资产不存在`）；删除失败 500；返回 `{success, message:'资产已删除'}`；磁盘文件保留 |

- 类型校验常量：`IMAGE_TYPES`/`AUDIO_TYPES`（MIME 白名单）与 `IMAGE_EXTS`/`AUDIO_EXTS`（扩展名回退，兜底 `application/octet-stream` 客户端）。判定为「MIME 不在白名单 **且** 扩展名不在回退集」才拒绝（400 `只能上传音频/图片文件（收到 xxx）`）。
- 落盘层 `save_upload` 仍强制扩展名白名单（音频 `.mp3/.wav/.m4a/.aac/.flac/.ogg`，默认扩展 `.mp3`；图片同 uploads 线，默认 `.png`），防伪造 content-type 的危险扩展名。
- 登记元信息：`meta={"size_kb": <KB, 一位小数>}`，`name` 取原始文件名（空则落盘文件名）。

### 持久层（backend/core/persistence/session_manager.py）

- 表 `session_assets`：`asset_id TEXT PRIMARY KEY`(uuid4)、`session_id TEXT NOT NULL`、`asset_type TEXT NOT NULL`、`name TEXT NOT NULL`、`file_path TEXT NOT NULL`、`meta TEXT DEFAULT '{}'`、`created_at TEXT NOT NULL`；无 FOREIGN KEY 约束（与 sessions 仅逻辑关联）。
- `add_asset`：uuid4 主键 + INSERT，返回新记录 dict（meta 为 dict）。
- `list_assets(session_id, asset_type=None)`：过滤或全量，`ORDER BY created_at DESC`；行转 dict 时 meta 缺省回退 `{}`。
- `get_asset(asset_id)`：按 id 查单条（不限会话，路由层再校验 session 归属）。
- `delete_asset(session_id, asset_id)`：按 asset_id + session_id 双条件 DELETE，只删记录不删磁盘文件。
- `delete_session`：同一事务内先删 `step_results` → 再删 `session_assets` → 最后删 `sessions`（级联清理资产记录，磁盘文件保留）。

### 前端（frontend/src/api/client.ts + MaterialGenerateModal.tsx）

- `uploadApi.uploadImage(file)`：FormData POST `/uploads/image`，返回 `{file_path, url}`。
- `assetApi`：`list(sessionId, assetType?)` GET `/assets/{id}`、`upload(sessionId, assetType, file)` POST `/assets/{id}/upload?asset_type=`、`remove(sessionId, assetId)` DELETE `/assets/{id}/{assetId}`。
- `MaterialGenerateModal`（AI 生成素材图弹窗，antd Upload）：`handleUpload` 调 `uploadApi.uploadImage`，成功后把 `file_path` 追加到 `uploadPaths`；提交时 `uploadPaths` 作为 `reference_paths` 传 `stepApi.generateSegmentMaterial`（与 @ 素材引用、素材池选择并列的第三种参考图来源）。
- TS 类型 `SessionAsset`：`asset_id`/`session_id`/`asset_type: 'audio' | 'image'`/`name`/`file_path`/`meta`/`created_at`。

### 音频资产消费链（视频生成）

`workflow_v2.py`（步骤7 ComfyUI 整段生成）→ `session_manager.list_assets(session_id, asset_type="audio")` → `comfyui_service.generate_full_video(audio_assets=...)`：真实调用链路先把全部材料路径（首帧图 + 音频资产 `file_path` + 分镜参考图）经 `client.upload_file` 上传到远程 ComfyUI（第 458-464 行），再在 timeline 中按 `asset.get("audio_mode", "reference")` 定义音频素材（id `aud1`、`aud2`...），作为整段视频生成的参考音频。

## 依赖与复用关系

- 依赖: FastAPI（UploadFile/File/Depends/HTTPException）、`backend/deps.py`（get_session_manager / load_video_session）、`backend/api/v1/_upload.py`（save_upload 共用）、SQLite（data/sessions.db，session_assets 表）、StaticFiles（`/static` 挂载）；前端 axios（client.ts，baseURL `/api/v1`）、antd（MaterialGenerateModal 的 Upload/message）
- 被依赖: `backend/core/agents/workflow_v2.py`（音频资产 → ComfyUI 参考音频）、`backend/core/services/comfyui_service.py`（audio_assets 参数）、`frontend/src/components/workflow/material/MaterialGenerateModal.tsx`（uploadApi 参考图上传）
- 可复用组件: `save_upload`（任何新增上传路由的统一落盘入口：白名单/uuid 命名/分块限流/异常清理）

## 注意事项

- **assetApi 前端无消费方**：`assetApi`（client.ts:203）目前只在 client.ts 定义，grep 全前端无页面/组件调用（docstring 所称「素材管理台：音频管理/素材管理」UI 未接线）；但后端 API 与 workflow_v2 音频消费链完整可用，可经 API 直接操作。
- **删除不清理磁盘**：`delete_asset` 与 `delete_session` 均只删 `session_assets` 记录，`static/uploads`（及 `audio` 子目录）下的文件永久保留，需人工清理。
- **file_path 存的是本地相对路径**：`assets.py` 的 `relative_path = f"{file_path}"` 实际写入 `Path` 的字符串（如 `static/uploads/audio/xxx.mp3`，相对后端工作目录）；`uploads.py` 则手工拼 `static/uploads/{name}`。ComfyUI 消费端按本地文件路径直接读取。
- **audioMode 恒为默认值**：timeline 构造读取 `asset.get("audio_mode", "reference")`，但 `add_asset` 登记的记录字段（asset_id/session_id/asset_type/name/file_path/meta/created_at）并无 `audio_mode` 键（meta 仅含 size_kb），因此当前所有音频素材的 audioMode 均为默认 `reference`，无入口配置其他模式。
- **双保险校验**：MIME 校验在路由层（宽松：MIME 或扩展名任一命中即可过），扩展名白名单在落盘层（强制）；因此伪造 content-type 的危险文件会在落盘层被 400 拦截。
- **上限 20MB**：`MAX_UPLOAD_SIZE` 对两条线统一生效，音频大文件（如长 BGM）可能超限。
- **会话隔离靠路由层**：`get_asset` 不校验会话，`delete_asset` 由路由层先比对 `asset["session_id"] != session_id` 抛 404；`list_assets` 天然按 session_id 过滤。
- **上传路由无鉴权**：两条上传路由无登录态/鉴权依赖，仅靠 CORS 白名单（localhost:5173/3000）限制浏览器来源。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — 基于源码分析自动生成 |
