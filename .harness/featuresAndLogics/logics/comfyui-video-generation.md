---
name: ComfyUI 时间轴视频生成逻辑
摘要: 构建 5+17n 帧对齐 timeline 注入 ComfyUI 生成长视频，默认 mock 兜底
tags: comfyui, 视频生成, timeline, mock
---

# ComfyUI 时间轴视频生成逻辑

**最后更新:** 2026-09-19

## 逻辑概述

核心实现位于 `backend/core/services/comfyui_service.py`：将上游 `workflow_v2.py` 步骤 7（generate_videos）收集的分镜（segments）、首帧图、参考图与音频素材，构建为满足帧数约束的 timeline 数据（timeline_data），注入 API 格式工作流模板后提交 ComfyUI，生成段间带重叠（overlap）的长视频。核心要点：

- **帧数约束体系**：fps 硬编码为 24（`COMFYUI_TIMELINE_FPS`，非环境变量）；合法段长必须满足 `length = 5 + 17n`（`SEGMENT_FRAME_BASE=5`、`SEGMENT_FRAME_STEP=17`）且 ≤ `MAX_SEGMENT_FRAMES=3592`。
- **段间重叠衔接**：overlap 帧数同样按 `5+17n` 对齐；首段 `start=0`，后续段 `start = prev_end - overlap_frames`、`end = start + seg_frames`，不允许段间空隙或未前进。
- **两次构建、两次校验**：先用本地文件名 build + validate 快速失败；素材上传 ComfyUI 后再用服务端返回的文件名重建 timeline 并复验。
- **mock 默认开启**：`COMFYUI_MOCK` 默认 `'true'`，即默认跳过全部 HTTP 调用，用 `cv2.VideoWriter` 本地生成占位视频兜底；真实生成需显式关闭 mock。
- **audioMode 素材模型**：图片素材（首帧图 + 参考图）与音频素材（含 audioMode）注册在 timeline 顶层，各段通过 id 列表引用。

### 配置与常量

| 常量 | 值 / 来源 | 说明 |
|------|-----------|------|
| `BASE_DIR` | `backend/`（config.py 的 parent.parent） | 项目后端根目录 |
| `COMFYUI_BASE_URL` | env `COMFYUI_BASE_URL`，默认 `'http://127.0.0.1:8188'` | ComfyUI 服务地址 |
| `COMFYUI_MOCK` | env `COMFYUI_MOCK`，默认 `'true'` | **默认开启 mock**；`lower() in ('1','true','yes')` 视为真 |
| `COMFYUI_TIMELINE_FPS` | 24（硬编码常量，非 env） | 时间轴帧率 |
| `COMFYUI_WORKFLOW_PATH` | `BASE_DIR / 'comfyui_workflow.json'` | API 格式工作流模板（**该文件当前不在仓库中**，见注意事项） |
| `MAX_AUDIOS_PER_SEGMENT` | 3 | 每段音频数上限 |
| `MAX_IMAGES_PER_SEGMENT` | 9 | 每段图片数上限 |
| `MAX_SEGMENT_FRAMES` | 3592 | 单段最大帧数 |
| `SEGMENT_FRAME_BASE` | 5 | 段长对齐基数 |
| `SEGMENT_FRAME_STEP` | 17 | 段长对齐步长 |
| `VIDEO_SAVE_DIR` | `Path('static/videos')`（backend/core/utils/path_utils.py:5，相对路径） | 生成视频保存目录 |

### 帧数对齐算法

- `_align_segment_frames(raw_frames)`：`n = max(0, round((raw - 5) / 17))`，`frames = 5 + 17n`，再 `min(frames, 3592)`——对齐到最近合法段长。
- `_align_overlap_frames(raw_frames)`：`raw <= 0` 返回 0；否则 `n = max(1, round((raw - 5) / 17))`，返回 `5 + 17n`（最小 5）。
- 帧数换算：`seg_frames = _align_segment_frames(round(duration * fps))`，`duration` 取 `seg.get('duration', 15) or 15`（默认 15 秒）。
- overlap 换算：`overlap_frames = _align_overlap_frames(round(overlap_seconds * fps))`，`_overlap_frames` / `_overlap_seconds` 附加存于 timeline dict 顶层（`_` 前缀字段为调试附加，非 ComfyUI 必需）。

### timeline 数据结构（TimelineBuilder.build）

静态方法签名：`build(segments: list[dict], frame_image_paths: dict[int, str], audio_assets: list[dict] | None = None, overlap_seconds: float = 0.0, fps: int = COMFYUI_TIMELINE_FPS(=24), uploaded_files: dict[str, dict] | None = None, reference_image_paths: dict[int, list[str]] | None = None) -> dict`

- **顶层结构**：`{version: 5, fps, globalPrompt: '', selection: {start: 0, duration: max(1, prev_end // fps)}, videoAudioEnabled: True, videoClips: [], images, audios, segmentConfig: {count, activeIndex: 0, mode: 'timeline', segments}, _overlap_frames, _overlap_seconds}`。
- **每段结构**：`{startFrame, endFrame, images, audios, prompt}`，`prompt` 由 `build_segment_prompt` 生成。
- **图片素材 id**：首帧图为 `'img{idx+1}'`；参考图（reference_image_paths）为 `'ref{idx+1}_{n+1}'`；`file` 字段取 `uploaded_files[path]['name']`（已上传）或 `Path(path).name`（mock / 未上传）。
- **音频素材**：id `'aud{序号}'`，dict 含 `{id, file, audioMode}`，`audioMode` 取 `asset.get('audio_mode', 'reference')`。
- **每段素材分配**：`seg_images = [首帧图id]`（若有）+ `seg_ref_ids[idx]`；`seg_audios = audio_ids[:3]`——当前策略是把所有音频资产的前 3 个分配给每一段（代码注释明确此为当前策略）。
- **段提示词** `build_segment_prompt(seg)`：`parts = [content] + ['镜头运动: {camera_movement}']（若有）+ ['氛围: {atmosphere}']（若有）`，用 `'。'` 拼接非空项。

### 校验规则（TimelineBuilder.validate）

返回错误字符串列表（空列表 = 通过），校验项：

- `segmentConfig.mode` 必须为 `'timeline'`；`segmentConfig.count` 必须等于 `len(segments)`。
- 每段 `length = endFrame - startFrame` 满足 `(length - 5) % 17 == 0` 且 `length > 0`，且 `length <= 3592`。
- 首段 `startFrame` 必须为 0。
- `i > 0` 时：`overlap = prev_end - start` 不得 < 0（不允许空隙）；`overlap != 0` 时须满足 `overlap % 17 == 5`（代码以 `overlap % 17 != 5 % 17` 判断报错）；overlap 必须小于段长（`overlap >= length` 报错）；若 `end <= prev_end` 报"未前进"。
- 每段 images 数 ≤ 9，audios 数 ≤ 3。
- **已知遗漏**：仅校验每段素材计数，不校验 id 引用有效性。

## 关键流程

1. 入口与素材收集 — `workflow_v2.py` 步骤 7 `generate_videos` → `_step_generate_videos_comfyui(session_id, extra_prompt)`：`frame_image_paths` 取前置步骤 `generate_segment_frames` 结果的 `segment_frames[].first_image_path`（按 `segment_index` 映射，缺失首帧的分片不传参考图，仅靠提示词生成）；`reference_image_paths` 取 `segments[].reference_images[].image_path`（按 index 映射，http(s) 外链被过滤不上传）；`audio_assets` 取 `session_manager.list_assets(session_id, asset_type='audio')`（`backend/core/persistence/session_manager.py:663`）；`overlap_seconds` 取 `selected_episode['video_params'].get('overlap_seconds', 0)`；`extra_prompt` 以 `'。'` 追加到每段 `content` 后再生成。分片列表来源 `_get_video_segments`（workflow_v2.py:119）：优先读 legacy 步骤 `generate_segment_scripts` 结果，否则经 `get_workspace_store().read_storyboard`（`backend/core/persistence/workspace_store.py:788`）从工作区分镜文件读取，`duration` 取 `video_params.max_segment_duration` 默认 15。
2. 预构建与校验 — `generate_full_video(segments, frame_image_paths, audio_assets=None, overlap_seconds=0.0, reference_image_paths=None) -> dict` 先用未上传的本地文件名 `TimelineBuilder.build` 一遍并 `validate`，失败抛 `ValueError`。
3. mock 分支 — `VideoServiceComfyUI.mock` 为 True（`COMFYUI_MOCK` 默认 true）时跳过全部 HTTP：`asyncio.to_thread` 调 `_generate_mock_video`，输出 `VIDEO_SAVE_DIR / f'mock_comfyui_{uuid4hex8}.mp4'`，返回 `{success: True, video_path, timeline_data, mock: True, prompt_id: f'mock-{uuid4hex8}'}`。
4. 上传素材 — `upload_paths` = 首帧图路径集合 ∪ 音频 `file_path` ∪ 所有参考图路径，逐个 `await client.upload_file`（串行，无并发）。
5. 重建 timeline — 用 `uploaded_files`（文件名替换为 ComfyUI 返回的 `name`）重建 timeline 并再次 `validate`。
6. 加载模板并提交 — `load_workflow_template` 读 `backend/comfyui_workflow.json` → `inject_timeline_data` 将 `json.dumps(timeline_data, ensure_ascii=False)` 写入带 `timeline_data` 输入的节点 → `submit_prompt`（body 为 `{prompt: workflow, client_id: f'money-printer-{uuid4hex8}'}`）得到 `prompt_id`。
7. 轮询结果 — `wait_for_result`（`max_wait=1800.0s` 即 30 分钟、`poll_interval=5.0s`）循环 `get_history`，history 非空且 `status.completed` 或 `status.status_str == 'error'` 即返回；`status_str == 'error'` 时 `generate_full_video` 抛 `RuntimeError`（status 前 500 字符）。
8. 下载与结果组装 — `download_output` 遍历 `history['outputs']` 各节点，在 `'videos'/'gifs'/'images'` 键下找 `type=='output'` 且 filename 不以 `.png/.jpg/.jpeg/.webp` 结尾的条目（取第一个），`GET {base}/view` 流式下载（`aiter_bytes` 写文件）保存为 `VIDEO_SAVE_DIR / f'comfyui_{uuid4hex8}_{filename}'`；返回 `{success: True, video_path, timeline_data, mock: False, prompt_id}`。workflow_v2 侧组装：`result_data.generated_videos` 为按 timeline segment 逐段构造的列表（同一 `video_path` 重复，`duration = round((endFrame - startFrame) / fps, 2)`，`task_status='completed'`），`final_video` 含 `{video_path, prompt_id, mock, overlap_seconds, segment_count}`，并附完整 `timeline_data`。

## 涉及代码

- `backend/core/services/comfyui_service.py` — 核心实现：`TimelineBuilder`（build / validate / build_segment_prompt / 帧数对齐）、`ComfyUIClient`（模板加载、素材上传、提交、轮询、下载）、`VideoServiceComfyUI`（`generate_full_video` 编排与 `_generate_mock_video` 兜底）。
- `backend/core/config.py` — 配置常量（`BASE_DIR`、`COMFYUI_BASE_URL`、`COMFYUI_MOCK`、`COMFYUI_TIMELINE_FPS`、`COMFYUI_WORKFLOW_PATH`）。
- `backend/core/utils/path_utils.py` — `VIDEO_SAVE_DIR = Path('static/videos')`（第 5 行，相对路径）。
- `backend/core/agents/workflow_v2.py` — 上游调用方：步骤 7 `generate_videos` → `_step_generate_videos_comfyui`（含 `_get_video_segments` 分片来源），负责素材收集与结果组装。
- `backend/core/services/__init__.py` — 导出 `VideoServiceComfyUI`、`ComfyUIClient`、`TimelineBuilder`。
- `backend/comfyui_workflow.json` — **当前仓库中不存在该文件**（2026-09-19 已验证）。`COMFYUI_WORKFLOW_PATH` 指向此处；非 mock 模式下 `load_workflow_template` 会抛 `FileNotFoundError`，需先将从 ComfyUI 导出的 API 格式工作流（含带 `timeline_data` 输入的 MiniMaxH3TimelinePlanner 节点）放到该路径。

## 相关功能

- 分镜首帧图生成（workflow_v2 前置步骤 `generate_segment_frames`，产出 `segment_frames[].first_image_path`）
- 会话音频资产（`session_manager.list_assets(session_id, asset_type='audio')`，实现位于 `backend/core/persistence/session_manager.py:663`）
- 视频工作流全景 — 见 `features/video-workflow.md`
- 素材上传与资产 — 见 `features/upload-and-assets.md`
- 文件化工作区（分镜文件读取 `read_storyboard`）— 见 `logics/workspace-store.md`

## 注意事项

- **mock 默认开启**：`COMFYUI_MOCK` 默认 `'true'`（真值判定 `lower() in ('1', 'true', 'yes')`），联调真实 ComfyUI 前必须显式关闭，否则静默走本地占位视频、不发任何 HTTP。
- **工作流模板缺失**：`backend/comfyui_workflow.json` 当前不存在；关闭 mock 后真实链路会在 `load_workflow_template` 处抛 `FileNotFoundError`（提示需导出 API 格式工作流）。`inject_timeline_data` 遍历 `workflow.values()` 中所有 dict 节点、替换 `node['inputs']['timeline_data']`，找不到任何带该输入的节点时抛 `ValueError('工作流模板中未找到带 timeline_data 输入的节点')`。
- **mock 视频生成细节**：仅使用 `cv2.VideoWriter` 写入（fourcc `'mp4v'`，分辨率 1280×720，fps 取 `timeline['fps']` 默认 24，无视频读取/解码逻辑）；每段按 6 色循环着色，亮度系数 `k = 0.85 + 0.15 * |((t / max(duration, 0.01)) * 2) % 2 - 1|` 动态变化；叠加文字 `'[ComfyUI MOCK VIDEO]'`、`'Segment i/n'`、`'t=x.xs/durs'` 与段提示词（截断 60 字符）；段间 overlap 区间（`i>0` 且 `s < overlap_frames`）与前一段纯色帧 `addWeighted` 线性渐变（`alpha = 1 - (s+1)/overlap_frames`）；整体经 `asyncio.to_thread` 执行避免阻塞事件循环。
- **帧数硬约束**：段长必须 `(length-5) % 17 == 0` 且 ≤ 3592；overlap 非 0 时必须 `overlap % 17 == 5` 且小于段长；首段 `startFrame` 必须为 0；不允许空隙（overlap < 0）与未前进（`end <= prev_end`）。修改 duration / overlap 相关逻辑时必须维持该对齐关系。
- **每段素材上限**：images ≤ 9（`MAX_IMAGES_PER_SEGMENT`）、audios ≤ 3（`MAX_AUDIOS_PER_SEGMENT`）；validate 不校验 id 引用有效性。
- **HTTP 客户端行为**：`ComfyUIClient` 的 `base_url` 默认 `COMFYUI_BASE_URL`（rstrip('/')）、timeout 默认 120.0 秒、每次请求新建 `httpx.AsyncClient`；`upload_file` 先 `resolve_project_path(file_path)`，按扩展名映射 MIME（png/jpg/jpeg/webp/mp3/wav/m4a/aac/flac，其余 `application/octet-stream`），POST `/upload/image`，返回 `{name: data.get('name', 本地名), subfolder: data.get('subfolder', '')}`；`submit_prompt` 响应无 `prompt_id` 抛 `ValueError`；`get_history` 返回 `response.json().get(prompt_id, {})`；`download_output` 未找到输出抛 `ValueError`（含 outputs 前 500 字符）；`wait_for_result` 超时抛 `TimeoutError`。
- **selection.duration 整除截断**：`selection.duration = max(1, prev_end // fps)` 为整除截断值。
- 待补充：远程 MiniMaxH3TimelinePlanner 节点对 timeline_data 的真实消费行为（仅从后端代码推断约定）。
- 待补充：`selection.duration = max(1, prev_end // fps)` 的整除截断是否满足远程要求。
- 待补充：音频分配策略（每段固定取前 3 个音频）是否有更细粒度分配计划。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修订：确认 `backend/comfyui_workflow.json` 不存在并落定结论；修正 mock 视频描述（删除无代码依据的 VideoCapture 表述，补全亮度公式）；补充 `_get_video_segments` / `list_assets` / `read_storyboard` 源码位置；相关功能链接到实际文档 |
