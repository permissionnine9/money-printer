---
name: ComfyUI 时间轴视频生成逻辑
摘要: 构建 5+17n 帧对齐 timeline 注入 ComfyUI 生成长视频（两段式导入/执行 + UI 工作流落盘远程 + SSH 隧道部署），默认 mock 兜底
tags: comfyui, 视频生成, timeline, mock, MiniMaxH3, SSH隧道
---

# ComfyUI 时间轴视频生成逻辑

**最后更新:** 2026-09-21

## 逻辑概述

编排层位于 `backend/core/workflows/video_workflow.py`（自 `backend/core/agents/workflow_v2.py` 迁出，类名 `VideoCreationWorkflowV2` 不变）：将分镜（segments）、首帧图、参考图与音频素材收集后，交由 `backend/core/services/comfyui_service.py` 的 `TimelineBuilder` 构造满足帧数约束的 timeline 数据（timeline_data），注入 API 格式工作流模板后提交 ComfyUI，生成段间带重叠（overlap）的长视频。核心要点：

- **两段式链路优先**：「导入到 ComfyUI」（prepare_comfyui_import：上传素材 + 注入 timeline_data + UI 版工作流落盘远程）→「开始生成」（_execute_imported_videos 执行已注入的工作流）；无导入暂存或勾选不一致时回退一步式 `generate_full_video` 全流程。
- **帧数约束体系**：fps 硬编码为 24（`COMFYUI_TIMELINE_FPS`，非环境变量）；合法段长必须满足 `length = 5 + 17n`（`SEGMENT_FRAME_BASE=5`、`SEGMENT_FRAME_STEP=17`）且 ≤ `MAX_SEGMENT_FRAMES=3592`。
- **段间重叠衔接**：overlap 逐段取自分镜的 `overlap` 字段（第 3 步分镜管理配置的「与上一分镜重叠秒数」，首段无上一段恒为 0），帧数同样按 `5+17n` 对齐；后续段 `start = prev_end - overlap_frames`、`end = start + seg_frames`，不允许段间空隙或未前进。
- **两次构建、两次校验**：先用本地文件名 build + validate 快速失败；素材上传 ComfyUI 后再用服务端返回的文件名重建 timeline 并复验。
- **mock 默认开启**：`COMFYUI_MOCK` 默认 `'true'`，即默认跳过全部 HTTP 调用，用 `cv2.VideoWriter` 本地生成占位视频兜底；真实生成需显式关闭 mock。
- **audioMode 素材模型**：图片素材（首帧图 + 参考图）与音频素材（含 audioMode）注册在 timeline 顶层，各段通过 id 列表引用。

### 配置与常量

| 常量 | 值 / 来源 | 说明 |
|------|-----------|------|
| `BASE_DIR` | `backend/`（config.py 的 parent.parent） | 项目后端根目录 |
| `COMFYUI_BASE_URL` | env `COMFYUI_BASE_URL`，默认 `'http://127.0.0.1:8188'` | ComfyUI 服务地址（经 SSH 隧道指向远程） |
| `COMFYUI_MOCK` | env `COMFYUI_MOCK`，默认 `'true'` | **默认开启 mock**；`lower() in ('1','true','yes')` 视为真 |
| `COMFYUI_TIMELINE_FPS` | 24（硬编码常量，非 env） | 时间轴帧率 |
| `COMFYUI_WORKFLOW_PATH` | `comfyUI-flow/ComfyUI-MiniMaxH3-TimelineDirector/example_workflows/MiniMaxH3全功能合一完全体导演台工作流_api.json` | API 格式工作流模板；由 comfyUI-flow 工程 `scripts/build_comfyui_workflow_template.py` 从 UI 工作流生成（工作流改版后重跑） |
| `COMFYUI_WORKFLOW_UI_PATH` | 同目录 `MiniMaxH3全功能合一完全体导演台工作流.json` | **新增** UI 格式工作流模板；「导入到 ComfyUI」注入后写服务器 workflows 库用 |
| `RESOLUTION_OPTIONS` | `["480p", "720p", "1080p", "4K"]` | 视频分辨率选项，**新增 "480p" 档** |
| `MAX_AUDIOS_PER_SEGMENT` | 3 | 每段音频数上限 |
| `MAX_IMAGES_PER_SEGMENT` | 9 | 每段图片数上限 |
| `MAX_SEGMENT_FRAMES` | 3592 | 单段最大帧数 |
| `SEGMENT_FRAME_BASE` | 5 | 段长对齐基数 |
| `SEGMENT_FRAME_STEP` | 17 | 段长对齐步长 |
| `VIDEO_SAVE_DIR` | `Path('static/videos')`（backend/core/utils/path_utils.py，相对路径） | 生成视频保存目录 |

### 部署体系与连接管理

- **comfyUI-flow/**（git 未跟踪目录）= 第三方开源插件仓 `ComfyUI-MiniMaxH3-TimelineDirector`（MiniMax H3 无限时长分段长视频生成：分段续接 AV Latent、同种子、音画合并；含 Python 自定义节点 / 前端 js / example_workflows）。工作流模板（API 版与 UI 版）均取自其 `example_workflows/`。
- **start_comfyui_tunnel.sh**（97 行）：SSH 隧道把远程 `gz15-a100:8188` 转发到本地 `127.0.0.1:8188`，后端经 `COMFYUI_BASE_URL` 访问远程 ComfyUI API；凭据复用 `~/.claude/skills/comfyui-restart/hosts.json` 的 gz15-a100 条目（与 comfyui-restart skill 共用，不硬编码）；幂等（已通直接退出）、断线自动重连、PID 文件管理（`/tmp/comfyui_tunnel_gz15-a100.pid`）。
- **start_all.sh** 集成：随主服务一起拉起隧道（`bash start_comfyui_tunnel.sh &` 记 TUNNEL_PID，cleanup 时 `kill -- -TUNNEL_PID`）。
- **settings API**（backend/api/v1/settings.py，121 行）：
  - `GET /api/v1/settings/comfyui-connection` — 读 hosts.json 的 gz15-a100 条目（密码脱敏为 `password_set` 布尔），并探测 `http://127.0.0.1:8188/system_stats` 返回连通状态 `connected`。
  - `PUT /api/v1/settings/comfyui-connection` — 写回 hosts.json（password 留空 = 保留原密码）→ `_stop_tunnel`（PID 文件 kill + `pkill -f start_comfyui_tunnel.sh` 兜底，幂等）→ 1s 后重启隧道脚本（`Popen(start_new_session=True)` 脱离 API 进程会话）→ 35s 内每 2s 轮询探测连通，返回 `connected` 与提示信息。
  - 前端 `ComfyUIConnectionModal`（MainLayout 顶栏云服务器图标）消费。

### 帧数对齐算法

- `_align_segment_frames(raw_frames)`：`n = max(0, round((raw - 5) / 17))`，`frames = 5 + 17n`，再 `min(frames, 3592)`——对齐到最近合法段长。
- `_align_overlap_frames(raw_frames)`：`raw <= 0` 返回 0；否则 `n = max(1, round((raw - 5) / 17))`，返回 `5 + 17n`（最小 5）。
- 帧数换算：`seg_frames = _align_segment_frames(round(duration * fps))`，`duration` 取 `seg.get('duration', 15) or 15`（默认 15 秒）。
- overlap 换算（**逐段**）：`overlap_frames = _align_overlap_frames(round(seg['overlap'] * fps))`（`i > 0` 时；首段恒 0）；`_overlap_frames` / `_overlap_seconds` 为逐段列表存于 timeline dict 顶层（`_` 前缀字段为调试附加，非 ComfyUI 必需）。

### timeline 数据结构（TimelineBuilder.build）

静态方法签名：`build(segments: list[dict], frame_image_paths: dict[int, str], audio_assets: list[dict] | None = None, fps: int = COMFYUI_TIMELINE_FPS(=24), uploaded_files: dict[str, dict] | None = None, reference_image_paths: dict[int, list[str]] | None = None, global_prompt: str = "") -> dict`（overlap_seconds 参数已移除，重叠逐段取自 seg['overlap']）

- **顶层结构**：`{version: 5, fps, globalPrompt, selection: {start: 0, duration: max(1, prev_end // fps)}, videoAudioEnabled: True, videoClips: [], images, audios, segmentConfig: {count, activeIndex: 0, mode: 'timeline', segments}, _overlap_frames, _overlap_seconds}`。
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

1. 同步入口 — `run_generate_videos_sync(session_id)`（video_workflow.py:312）：供 sync 路由 BackgroundTasks 线程池调用，线程内 `asyncio.run(step_generate_videos(...))`；门禁与勾选集合以 `mark_videos_generating` 落盘的 `result_data.segment_indexes` 为准（后台任务不重算，生成期间取消某分镜 configured 不中断任务）。
2. 生成前状态与备份 — `mark_videos_generating(session_id, segment_indexes=...)`（:226）：门禁 = 分镜大纲完成 + ≥1 个分镜 configured（经 `_resolve_generation_segments`）；写 `_generating` 初始状态落盘；上次生成已完成时先 `reset_current_step` 回退步骤状态，旧分段视频逐段备份 `_old_video_path`/`_old_video_id`、旧最终视频备份 `_old_final_video`（生成中重复调用不备份），`_backed_up_count` 计数——前端 hasBackup 判断基于 `_backed_up_count`/`_old_video_path`；校验失败抛 WorkflowError（main.py 全局 handler 转 HTTP detail）。`restore_videos_backup`（:273）：`_generating` 中禁止恢复；逐段回填 `_old_video_path`（task_status=completed、duration 回默认 5.0）+ `_old_final_video` 回填 final_video；无可恢复数据抛 WorkflowError。
3. 勾选解析 — `_resolve_generation_segments`（:157）/`_configured_segment_indexes`（:144）：支持 `segmentIndexes` 指定段生成（缺省 = 全部已配置分镜；空列表报「请至少勾选一个分镜」）；gate=True 时校验勾选均在 configured 集合内，gate=False 只按 index 过滤不重跑门禁（后台任务消费路径）；连续性校验（分镜编号须严格相邻不可跳选，与前端勾选规则一致）。
4. 两段式·阶段一「导入到 ComfyUI」— `prepare_comfyui_import(session_id, segment_indexes, global_prompt)`（video_workflow.py:397）→ `comfyui_service.prepare_import`（comfyui_service.py:533）：TimelineBuilder.build + validate → 非 mock 上传全部材料（首帧图 ∪ 音频 file_path ∪ 参考图，串行）→ 用上传结果重建 timeline 复验 → `inject_timeline_data` 注入 API 模板 → **UI 版工作流同步落盘远程**（`inject_timeline_data_ui` 注入 UI 模板 + `save_ui_workflow`：`POST {base}/minimax_h3_timeline/save_workflow`（TimelineDirector 自定义节点端点），文件名 `导入_{会话ID前8}.json`，落服务器 `user/default/workflows/money-printer/` 供 ComfyUI 网页打开检查/微调；失败仅告警不阻断）。global_prompt 为空时 `_auto_global_prompt` 自动注入本集戏剧基调。导入暂存经 `session_manager.save_aux_state(session_id, 'comfyui_import')` 存 step_results（不推进步骤状态机），返回摘要（segment_indexes/segment_count/image_count/audio_count/total_duration/global_prompt/mock/ui_workflow_name/comfyui_url/imported_at）。
5. 全局提示词自动提取 — `_auto_global_prompt`（:361）：用户未填时从容错提取本集戏剧基调（整条时间轴语境统一）。best-effort：选集读取异常 / episode 读取异常 / read_story_logic 异常均返回空串；组成 = 「本集剧情语境：logline（截 200 字）」+「全剧基调：故事逻辑『情感基调与题材』行（正则 `[ \t]*` 只吞同行空白不跨行吸入下一行；截到首个句号，丢弃同行拖带的后续字段；上限 150 字）」+ 尾句「所有分镜共享以上语境…」；回归测试 `tests/manual/test_narrative_prompt_chain.py`。
6. 两段式·阶段二「开始生成」— `step_generate_videos` 先 `_get_imported_state`（:348）：读 comfyui_import 暂存，无 timeline_data 或 segment_indexes 与本次勾选不一致返回 None（重走全流程）；命中则 `_execute_imported_videos`（:463）→ `comfyui_service.execute_imported`（提交工作流 → 轮询 → 下载；mock 时 workflow 为 None 本地合成演示视频）→ `_finalize_video_result`。
7. 一步式全流程 — `_step_generate_videos_comfyui`（:591）：`_collect_generation_materials`（gate=False）→ `comfyui_service.generate_full_video`（一步式无用户填写入口，global_prompt 亦走 `_auto_global_prompt`）→ `_finalize_video_result`；异常统一 `_save_video_failure` 落失败快照（`_generating=False`/`_success=False`/error）。`generate_full_video` 内部即 prepare_import + execute_imported 的组合（regenerate/legacy 链路用）。
8. 素材收集 — `_collect_generation_materials`（:482，两段式与一步式共用）：`frame_image_paths` 取前置步骤 `generate_segment_frames` 结果的 `segment_frames[].first_image_path`（按 `segment_index` 映射，缺失首帧的分片不传参考图，仅靠提示词生成）；`reference_image_paths` 取 `segments[].reference_images[].image_path`（按 index 映射，http(s) 外链被过滤不上传）；`audio_assets` 取 `session_manager.list_assets(session_id, asset_type='audio')`；`extra_prompt` 以 `'。'` 追加到每段 `content` 后再生成。分片列表来源 `get_video_segments`（video_workflow.py:113）：优先读 legacy 步骤 `generate_segment_scripts` 结果，否则经 `get_workspace_store().read_storyboard` 从工作区分镜文件读取，`duration` 取 `video_params.max_segment_duration` 默认 15。
9. 结果组装 — `_finalize_video_result`（:532，两段式与一步式共用）：`generated_videos` 按 timeline segment 逐段构造（勾选子集时回填原始分镜 index：`segment_index = seg_indexes[j]`；同一 `video_path` 重复，`duration = round((endFrame - startFrame) / fps, 2)`，`task_status='completed'`），`final_video` 含 `{video_path, prompt_id, mock, overlap_seconds（逐段 `_overlap_seconds` 列表合计，兼容旧单值）, segment_count}`，并附完整 `timeline_data`；落盘后将 session 状态置 completed。
10. mock 分支 — `VideoServiceComfyUI.mock` 为 True（`COMFYUI_MOCK` 默认 true）时跳过全部 HTTP：prepare_import 跳过上传与模板加载（workflow 为 None，timeline 用本地文件名）；execute_imported 经 `asyncio.to_thread` 调 `_generate_mock_video` 本地合成（详见注意事项），返回 `{success: True, video_path, timeline_data, mock: True, prompt_id: f'mock-{uuid4hex8}'}`。
11. 轮询与下载 — `wait_for_result`（`max_wait=2400.0s` 即 40 分钟、`poll_interval=5.0s`）循环 `get_history`，history 非空且 `status.completed` 或 `status.status_str == 'error'` 即返回；error 时抛 `RuntimeError`（status 前 500 字符）。`download_output` 遍历 history outputs 各节点，在 `'videos'/'gifs'/'images'` 键下找 `type=='output'` 条目，`GET {base}/view` 流式下载保存为 `VIDEO_SAVE_DIR / f'comfyui_{uuid4hex8}_{filename}'`。
12. 前端（Step6Videos.tsx）— 分镜轨道连续勾选（与后端连续性校验一致）；`splitContiguousRuns` 取最长连续段兜底；`importComfyUI`（传 segmentIndexes + globalPrompt，展示导入摘要）→ `startComfyUIVideo` 触发后台生成；备份恢复入口（hasBackup）；`usePolling maxPolls: 200` 轮询兜底防死轮询。

## 涉及代码

- `backend/core/workflows/video_workflow.py` — 编排层（自 agents/workflow_v2.py 迁出，类名 VideoCreationWorkflowV2 不变）：`run_generate_videos_sync`、`mark_videos_generating` / `restore_videos_backup`、`prepare_comfyui_import` / `_execute_imported_videos` / `_get_imported_state`、`_auto_global_prompt`、`_collect_generation_materials`、`_resolve_generation_segments` / `_configured_segment_indexes`、`get_video_segments`、`_finalize_video_result` / `_save_video_failure`、`_step_generate_videos_comfyui`。
- `backend/core/services/comfyui_service.py` — 服务层：`TimelineBuilder`（build / validate / build_segment_prompt / 帧数对齐）、`ComfyUIClient`（API 模板加载、UI 模板加载 `load_workflow_ui_template`、`save_ui_workflow`、素材上传、提交、轮询、下载、`inject_timeline_data` / `inject_timeline_data_ui`）、`VideoServiceComfyUI`（`prepare_import` / `execute_imported` / `generate_full_video` 编排与 `_generate_mock_video` 兜底）。
- `backend/core/config.py` — 配置常量（`BASE_DIR`、`COMFYUI_BASE_URL`、`COMFYUI_MOCK`、`COMFYUI_TIMELINE_FPS`、`COMFYUI_WORKFLOW_PATH`、`COMFYUI_WORKFLOW_UI_PATH`、`RESOLUTION_OPTIONS`）。
- `backend/api/v1/settings.py` — ComfyUI 连接设置 API（GET/PUT `/api/v1/settings/comfyui-connection`，读写 hosts.json + 隧道重启探测）。
- `start_comfyui_tunnel.sh` / `start_all.sh` — SSH 隧道脚本与主服务集成拉起（TUNNEL_PID + cleanup）。
- `comfyUI-flow/ComfyUI-MiniMaxH3-TimelineDirector/` — 第三方插件仓（未跟踪）：工作流模板（example_workflows/，API 版 + UI 版）与 `scripts/build_comfyui_workflow_template.py` 模板生成。
- `backend/core/utils/path_utils.py` — `VIDEO_SAVE_DIR = Path('static/videos')`（相对路径）。
- `backend/core/services/__init__.py` — 导出 `VideoServiceComfyUI`、`ComfyUIClient`、`TimelineBuilder`。
- `frontend/src/components/workflow/Step6Videos.tsx` — 前端消费（连续勾选 / splitContiguousRuns / importComfyUI / startComfyUIVideo / 备份恢复 / usePolling maxPolls=200）。
- `tests/manual/test_narrative_prompt_chain.py` — `_auto_global_prompt` 容错提取回归。

## 相关功能

- 分镜首帧图生成（前置步骤 `generate_segment_frames`，产出 `segment_frames[].first_image_path`）
- 会话音频资产（`session_manager.list_assets(session_id, asset_type='audio')`）
- 视频工作流全景 — 见 `features/video-workflow.md`
- 素材上传与资产 — 见 `features/upload-and-assets.md`
- 文件化工作区（分镜文件读取 `read_storyboard`）— 见 `logics/workspace-store.md`
- ComfyUI 连接设置（settings API + SSH 隧道 + comfyui-restart skill 共用 hosts.json）— 见本文件「部署体系与连接管理」一节

## 注意事项

- **mock 默认开启**：`COMFYUI_MOCK` 默认 `'true'`（真值判定 `lower() in ('1', 'true', 'yes')`），联调真实 ComfyUI 前必须显式关闭，否则静默走本地占位视频、不发任何 HTTP。
- **工作流模板来源**：模板已就位于 `comfyUI-flow/ComfyUI-MiniMaxH3-TimelineDirector/example_workflows/`（API 版 `_api.json` 与 UI 版 `.json`）；工作流改版后需重跑该工程 `scripts/build_comfyui_workflow_template.py` 重新生成。`inject_timeline_data` 遍历 `workflow.values()` 中所有 dict 节点、替换 `node['inputs']['timeline_data']`，找不到任何带该输入的节点时抛 `ValueError('工作流模板中未找到带 timeline_data 输入的节点')`。
- **UI 工作流落盘为增强能力**：`save_ui_workflow` 走 TimelineDirector 自定义节点端点 `/minimax_h3_timeline/save_workflow`，落盘失败仅 warning 不阻断导入（summary 的 ui_workflow_name 为 None）。
- **远程不可用提示**：prepare 阶段 `httpx.HTTPError` 统一转 WorkflowError，文案提示检查隧道 `./start_comfyui_tunnel.sh`；TimelineBuilder 校验失败（ValueError）转「导入到 ComfyUI 失败：…」。
- **mock 视频生成细节**：仅使用 `cv2.VideoWriter` 写入（fourcc `'mp4v'`，分辨率 1280×720，fps 取 `timeline['fps']` 默认 24，无视频读取/解码逻辑）；每段按 6 色循环着色，亮度系数 `k = 0.85 + 0.15 * |((t / max(duration, 0.01)) * 2) % 2 - 1|` 动态变化；叠加文字 `'[ComfyUI MOCK VIDEO]'`、`'Segment i/n'`、`'t=x.xs/durs'` 与段提示词（截断 60 字符）；段间 overlap 区间（`i>0` 且 `s < overlap_frames`）与前一段纯色帧 `addWeighted` 线性渐变（`alpha = 1 - (s+1)/overlap_frames`）；整体经 `asyncio.to_thread` 执行避免阻塞事件循环。
- **帧数硬约束**：段长必须 `(length-5) % 17 == 0` 且 ≤ 3592；overlap 非 0 时必须 `overlap % 17 == 5` 且小于段长；首段 `startFrame` 必须为 0；不允许空隙（overlap < 0）与未前进（`end <= prev_end`）。修改 duration / overlap 相关逻辑时必须维持该对齐关系。
- **每段素材上限**：images ≤ 9（`MAX_IMAGES_PER_SEGMENT`）、audios ≤ 3（`MAX_AUDIOS_PER_SEGMENT`）；validate 不校验 id 引用有效性。
- **HTTP 客户端行为**：`ComfyUIClient` 的 `base_url` 默认 `COMFYUI_BASE_URL`（rstrip('/')）、timeout 默认 120.0 秒、每次请求新建 `httpx.AsyncClient`；`upload_file` 先 `resolve_project_path(file_path)`，按扩展名映射 MIME（png/jpg/jpeg/webp/mp3/wav/m4a/aac/flac，其余 `application/octet-stream`），POST `/upload/image`，返回 `{name: data.get('name', 本地名), subfolder: data.get('subfolder', '')}`；`submit_prompt` 响应无 `prompt_id` 抛 `ValueError`；`get_history` 返回 `response.json().get(prompt_id, {})`；`download_output` 未找到输出抛 `ValueError`（含 outputs 前 500 字符）；`wait_for_result` 超时抛 `TimeoutError`。
- **selection.duration 整除截断**：`selection.duration = max(1, prev_end // fps)` 为整除截断值。
- **后台任务不重算门禁**：生成期间取消某分镜 configured 不应中断任务——执行阶段 `_collect_generation_materials`/`_resolve_generation_segments` 均 gate=False，只按 mark 落盘的 segment_indexes 过滤。
- 待补充：远程 MiniMaxH3TimelinePlanner 节点对 timeline_data 的真实消费行为（仅从后端代码推断约定）。
- 待补充：`selection.duration = max(1, prev_end // fps)` 的整除截断是否满足远程要求。
- 待补充：音频分配策略（每段固定取前 3 个音频）是否有更细粒度分配计划。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修订：确认 `backend/comfyui_workflow.json` 不存在并落定结论；修正 mock 视频描述（删除无代码依据的 VideoCapture 表述，补全亮度公式）；补充 `_get_video_segments` / `list_assets` / `read_storyboard` 源码位置；相关功能链接到实际文档 |
| 2026-09-21 | 部署体系 + 两段式链路落地 — 编排层自 agents/workflow_v2.py 迁至 core/workflows/video_workflow.py（类名不变）；COMFYUI_WORKFLOW_PATH 指向 comfyUI-flow 工程 example_workflows（模板已存在，删除「文件缺失」结论）、新增 COMFYUI_WORKFLOW_UI_PATH、RESOLUTION_OPTIONS 增 480p；新增部署体系节（comfyUI-flow 插件仓 / start_comfyui_tunnel.sh SSH 隧道 / start_all.sh 集成 / settings API GET+PUT comfyui-connection）；两段式「导入到 ComfyUI」（prepare_import 上传+注入+UI 工作流落服务器 user/default/workflows/money-printer/导入_{会话ID}.json、save_aux_state('comfyui_import') 不推进状态机）+ _execute_imported_videos；mark_videos_generating/restore_videos_backup 备份恢复；_auto_global_prompt 容错提取（test_narrative_prompt_chain.py 回归）；overlap 改逐段取自分镜 overlap 字段（首段恒 0，_overlap_* 为列表）；_resolve_generation_segments 支持 segmentIndexes 指定段生成；wait_for_result max_wait 更正为 2400s；补前端 Step6Videos 要点 |
