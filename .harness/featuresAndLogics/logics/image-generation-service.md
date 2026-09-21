---
name: OpenAI 兼容生图服务
摘要: OpenAI 兼容生图（配置校验/文生图/图生图/重试退避/同步缓存）+ ImageTaskService 统一三处生图任务状态机（依赖注入与持久层解耦）
tags: 生图服务, OpenAI兼容, 图像压缩, 模型配置, 生图任务状态机, 核心素材图, 素材库
---

# OpenAI 兼容生图服务

**最后更新:** 2026-09-21

## 逻辑概述

生图链路分两层：**ImageService（协议层）** 以 OpenAI Images API 兼容协议访问第三方生图端点（文生图 `POST {base_url}/images/generations`，图生图 `POST {base_url}/images/edits`）；**ImageTaskService（状态机层）** 统一三处生图任务的状态机流转与回写。

ImageService 协议层核心要点（本体基本不变，仅 28 行小改动；submit/poll 同步缓存语义不变）：

- **配置驱动，无内置默认端点**：`build_image_service_from_model_config` 经 ModelManager 读取 SQLite `image_models` 表，逐项校验 api_key / base_url / model_id，任一缺失即报错；未配置 model_config_id 时取 `model_type='image'` 的默认模型。
- **同步生成协议**：submit 时即完成 HTTP 请求并解析结果，写入实例级内存缓存 `_sync_results`（`dict[str,str]`）；`poll_i2i_task` 仅从缓存 pop 取回（`timeout`/`poll_interval` 参数未使用，保留签名兼容调用方）。
- **尺寸硬编码查表**：`_get_openai_image_size` 按 aspect_ratio × resolution 查表，未知 aspect_ratio 回退 16:9，未知 resolution 回退 720p 档，档位越界钳到最后档。
- **有限重试**：max_attempts=3，仅对 404/429/500/502/503 重试，线性退避 5s/10s；错误文本截断 300 字符。
- **参考图可选压缩**：图生图硬上限 4 张，压缩走 PIL（白底转 RGB、LANCZOS 缩放到最长边 1920、JPEG quality=85）。
- **落盘与归档分离**：b64 结果落盘 `static/images/`，再由 `archive_generated_image` 归档到 `static/images/{story}/{episode}/`，经 `backend/main.py` 的 `app.mount('/static')` 对外暴露。

ImageTaskService 状态机层（`backend/core/services/image_task_service.py`，131 行）：

- **纯「生图任务状态机」定位**：`ImageTaskSpec` dataclass（`image_id` / `prompt` / `reference_paths`）+ `ImageTaskService` 类，流转 insert(pending)→submit→processing→poll→completed/failed，统一三处消费：核心素材图批量 / 核心素材图单张重生成 / 分集素材图。
- **依赖注入与持久层解耦**：不持有 ImageService/ScriptManager——`image_service` 作参数传入；行状态回写经 `update_row(image_id, fields)` 回调适配 lookbook_images / episode_material_images（mat_*）两类表；`on_completed` 完成后钩子（返回 dict 时并入完成态回写，如归档改写 image_path/meta；不返回值时作纯回调，如 set_entity_lookbook 关联）；`interrupt` 取消（置位抛 WorkflowError「已取消」）；`pre_update` 提交前回写；`label` 错误前缀。构造参数 `error_cls` 统一业务异常类型（默认 WorkflowError，实际注入 ScriptWorkflowError / StoryboardError）。
- **prompt 模板中文化**：`backend/prompts/lookbook_prompts.md` 生图 prompt 从英文关键词堆砌改为中文一段式自然语言（130-220 中文字，用户可直接读懂修改）；人物实体产出三视图设定素材图（front/side/back 全身像并排、侧边带刻度身高比例尺并标注具体身高、干净中性背景无场景道具），场景实体产出场景全景素材图（全景定场构图、画面无人物）；概念「定妆照」统一更名「核心素材图」。
- **素材库（lookbook library）配套**：ScriptManager `list_completed_lookbooks()`（全局 completed 且 image_path 非空，跨剧本复用，created_at 倒序）、`insert_lookbook` 新增 image_path/meta 参数（素材库导入可直接落 completed 行）、`delete_script_data(keep_completed_lookbooks=True)`（级联清理时保留已完成核心素材图进素材库，未完成/失败行仍删除避免前端死轮询；分集素材图两种模式都全删）；上层 `backend/core/services/lookbook_library_service.py` 提供分组查询与复制导入。

## 关键流程

1. 构建服务 — `build_image_service_from_model_config(model_config_id=None)`（backend/core/services/image_service.py:25）：import ModelManager 读 `image_models` 表；有 model_config_id 时 `manager.get_model(id)`，配置不存在抛 `ImageModelNotConfiguredError(f'生图模型配置不存在: {id}')`；否则 `manager.get_default_model(model_type='image')`。随后逐项校验：无默认配置→'未配置默认生图模型...'；api_key/base_url/model_id strip 为空→各自报错。校验通过后 `ImageService(api_key, base_url, image_model)`。
2. 提交前置校验 — `submit_image_task(prompt, video_params, reference_images=None, model=None, compress_reference=False)`：`use_model = model or self._image_model`；use_model/api_key/base_url 任一缺失→返回 `{'success':False, 'error':_NOT_CONFIGURED_MSG}`（文案：'生图模型未配置（缺少 API Key / Base URL / 模型 ID），请在「模型管理」完成配置'）；否则转 `_submit_openai_image_task`，有 reference_images 走图生图，无则走文生图。
3. 计算尺寸 — 静态方法 `_get_openai_image_size(video_params)`：按 aspect_ratio 查硬编码尺寸表（16:9/9:16/1:1/4:3/3:2/2:3/21:9），未知回退 16:9；resolution（默认 '720p'）lower 后映射档位 `{'720p':0,'1080p':1,'2k':2,'4k':3}`（未知回退 0），取 `sizes[min(level, len(sizes)-1)]`（越界钳到最后档，如 21:9 只有 2 档）。
4. 发送请求 — `_submit_openai_image_task`：`request_id = f'openai-{uuid4().hex[:12]}'`，`httpx.AsyncClient(timeout=httpx.Timeout(300.0))`，请求头 `Authorization: Bearer {api_key}`。图生图：multipart 表单 `{model, prompt, size, n:1, quality:'auto', response_format:'b64_json'}`，遍历 `reference_images[:4]`（硬上限 4 张），每张经 `_load_reference_bytes` 读取（读不到的跳过），文件字段名统一 `'image'`、filename 固定 `'reference.png'`、mime 缺省 image/png。文生图：JSON body 同字段并加 `Content-Type: application/json`。
5. 重试与错误处理 — max_attempts=3，仅当 `response.status_code in (404,429,500,502,503)` 且非最后一次时 `sleep 5*(attempt+1)` 秒（5s/10s 线性退避）后重试，其他状态码或最后一次直接 break。非 200 → `{'success':False, 'error':f'HTTP {status}: {response.text[:300]}'}`（错误文本截断 300）。整个流程 try/except，异常→`{'success':False, 'error':str(e)}`。
6. 解析结果 — 取 `data['data'][0]`，优先 `item['url']`；无 url 且有 `item['b64_json']` 时 base64 解码写盘 `Path('static/images')/f'openai_{uuid4().hex[:8]}.png'`（`mkdir parents=True`），image_url 取该路径字符串；两者皆无→`{'success':False, 'error':f'响应中无图片: {str(data)[:300]}'}`。成功则 `self._sync_results[request_id]=image_url` 并返回 `{'success':True, 'request_id'}`。
7. 取回结果 — `poll_i2i_task(request_id, timeout=150, poll_interval=3)`：命中 `self._sync_results` 则 pop 并返回 `{'success':True, 'image_url'}`；未命中返回 `{'success':False, 'error':'任务结果不存在'}`（可能已被取回或提交失败）。
8. 参考图加载 — `_load_reference_bytes(image_path, compress)` 委托 `image_utils.load_image_bytes(image_path, compress, max_size=1920, quality=85)`：http(s):// 开头→httpx GET（timeout=60s）+ raise_for_status 取 content；否则 `resolve_project_path`（锚定项目根），不存在返回 `(None,None)` 并 warning。compress=True→`compress_image`（PIL 打开；RGBA/LA/P 转白底 RGB；最长边超限时 LANCZOS 等比缩放；保存 JPEG quality=85 optimize=True）。
9. 归档 — `archive_generated_image(source, story_name, episode_name, base_name, image_id)`：目标 `IMAGE_SAVE_DIR/sanitize_name(story_name)/sanitize_name(episode_name)`（`mkdir parents=True`）；扩展名 `_guess_ext`（仅接受 .png/.jpg/.jpeg/.webp 否则 .png）；文件名 `sanitize_name(base_name, max_len=40, fallback='material')+ext`，已存在则 `f'{stem}_{image_id}{ext}'`。source 为 URL→下载（timeout=60s, follow_redirects=True）write_bytes；本地路径→`resolve_project_path` 后 `shutil.move`。成功返回 `target.as_posix()`。
10. 生图任务状态机与三处消费（已核实）— 统一收敛到 `ImageTaskService`（构造注入：`ImageTaskService(ScriptWorkflowError)` @ script_workflow.py:71、`ImageTaskService(StoryboardError)` @ storyboard.py:86）：
    - run_batch（image_task_service.py:35-82）— 批量生图：逐张提交，第 2 张起 `await asyncio.sleep(submit_gap)` 间隔限流（默认 `IMAGE_REQUEST_TIME_GAP=12` 秒，config.py，避免生图服务限流；可传参覆盖）；提交成功登记 task_id 置 processing，提交失败/异常仅标 failed 不中断；全部提交后 `asyncio.gather` 并发轮询（poll_timeout=180 / poll_interval=5），单张失败标 failed 继续跑其余；interrupt（asyncio.Event）置位抛「已取消」；返回已提交成功的 (image_id, request_id) 列表。
    - run_single（image_task_service.py:84-131）— 单张同步生图：可选 `pre_update` 先行回写；提交/轮询失败标 failed 并抛 WorkflowError（`label` 拼错误前缀，如「素材图提交失败: …」「素材图生成失败: …」「素材图生成异常: …」）；成功时 `on_completed` 返回 dict 并入完成态回写（归档钩子改写 image_path/meta）；返回 poll 结果（含 image_url）。
    - 状态机流转：pending（insert）→ processing（登记 task_id）→ completed（写 image_path；on_completed 可追加 meta 等）/ failed（提交或轮询失败均置 failed）。
    - 消费场景（已核实）：核心素材图批量（script_workflow.py:708 run_batch，`update_row=scm.update_lookbook`，on_completed 回写实体 frontmatter `set_entity_lookbook`）；核心素材图单张重生成（script_workflow.py:733 run_single，pre_update 置 processing 并可选改 prompt）；分集素材图（storyboard.py:503 run_single，`label='素材图'`，`update_row=scm.update_episode_material`，on_completed 归档 `archive_generated_image` 改写 image_path/meta）。

## 涉及代码

- `backend/core/services/image_service.py` — 协议层核心实现：常量 IMAGE_COMPRESS_MAX_SIZE=1920 / IMAGE_COMPRESS_QUALITY=85、`ImageModelNotConfiguredError`、工厂 `build_image_service_from_model_config`、`ImageService`（构造、`_get_openai_image_size` 尺寸表、`submit_image_task`、`_submit_openai_image_task`、`_load_reference_bytes`、`poll_i2i_task`、`_sync_results` 缓存）。
- `backend/core/services/image_task_service.py` — 状态机层：`ImageTaskSpec` dataclass、`ImageTaskService`（run_batch :35-82 / run_single :84-131；update_row / on_completed / interrupt / pre_update / label / error_cls）。
- `backend/core/utils/image_utils.py` — 辅助实现：`compress_image(image_data, max_size, quality) -> (bytes, mime)`、`load_image_bytes(image_path, compress=False, *, max_size=1920, quality=85) -> (bytes|None, mime|None)`。
- `backend/core/utils/image_store.py` — 归档实现：`_INVALID_CHARS` 正则、`sanitize_name`、`_guess_ext`、`archive_generated_image`。
- `backend/core/utils/path_utils.py` — `resolve_project_path` 锚定项目根；IMAGE_SAVE_DIR（=Path('static/images')）/VIDEO_SAVE_DIR/PROJECT_ROOT 定义于此。
- `backend/core/persistence/model_manager.py` — ModelManager（SQLite image_models 表，模型配置读取）。
- `backend/core/persistence/script_manager.py` — 生图任务状态机两张表（lookbook_images / episode_material_images）及 update_lookbook / update_episode_material 回写；素材库配套 `list_completed_lookbooks` / `insert_lookbook(image_path, meta)` / `delete_script_data(keep_completed_lookbooks)`。
- `backend/core/services/lookbook_library_service.py` — 素材库（跨剧本复用）：`list_lookbook_library` 按剧本会话分组查询（当前剧本排第一，死会话孤儿行不进素材库）、`import_lookbook_from_library` 复制源行为当前会话新行（meta 记 imported_from 溯源）并回写实体锚点。
- `backend/prompts/lookbook_prompts.md` — 核心素材 prompt 模板（中文一段式自然语言；人物三视图设定图 / 场景全景图；风格优先级：用户指定 > 按题材判断）。
- `backend/main.py` — `app.mount('/static')` 静态对外暴露生成图片。
- `backend/core/agents/script_workflow.py`（:708 / :733）、`backend/core/agents/storyboard.py`（:503）— 消费方（核心素材图批量 / 单张重生成、分集素材图），经构造注入的 ImageTaskService 调用，已逐行核实。

## 相关功能

- 模型管理（image_models 表：默认 image 模型配置、api_key/base_url/model_id）
- 核心素材图（原「定妆照」）/ 分集素材图生成（script_workflow.py、storyboard.py 调用方链路）
- 素材库（lookbook library：跨剧本复用已完成核心素材图，前端 LookbookLibraryModal）
- 静态资源服务（/static 挂载，生成图片对外访问）

## 注意事项

- **未配置兜底**：submit 前置校验返回统一文案 `_NOT_CONFIGURED_MSG`；工厂层面无默认配置报'未配置默认生图模型...'，指定 id 不存在抛 `ImageModelNotConfiguredError`。无内置默认端点。
- **缓存生命周期**：`_sync_results` 是实例级内存缓存，跨 ImageService 实例/进程重启即失效。已核实三处消费均经 ImageTaskService：调用方在同一函数内 build 后把实例传入 run_batch/run_single 完成 submit→poll，缓存命中无跨实例风险；但若调用方在 submit 与 poll 之间重建服务（如跨请求轮询）则会得到'任务结果不存在'。
- **poll 参数为空壳**：`timeout=150`/`poll_interval=3` 未使用（run_batch/run_single 传 poll_timeout=180 / poll_interval=5 或 150/3 同样无效）；OpenAI 协议同步生成，submit 时结果已缓存，'任务结果不存在'可能表示已被取回或提交失败。
- **批量限流**：run_batch 间隔 `IMAGE_REQUEST_TIME_GAP=12` 秒（config.py），多张连续提交的限流间隔；需要更激进/保守的节奏时经 submit_gap 参数覆盖。
- **b64 落盘相对路径**：写的是 `Path('static/images')`（相对进程 CWD），未经 `resolve_project_path`（锚定 __file__ 推导的 PROJECT_ROOT）解析；当 CWD≠项目根时，落盘目录与参考图/归档源文件的锚定解析会分叉——运行时是否指向项目根取决于启动目录，代码无法确定。
- **参考图上限与容错**：硬上限 4 张（`reference_images[:4]`），读不到的跳过；files 全部为空→返回错误 `f'参考图无法读取: {reference_images[0]}'`。
- **filename 与实际 MIME 可能不符**：edits 请求 filename 固定 'reference.png' 但实际内容可能是压缩后的 JPEG——服务端是否按 MIME 处理无法从代码确定。
- **压缩异常兜底**：`compress_image` 任何异常返回 `(原始数据, 'image/png')`；`load_image_bytes` 异常返回 `(None,None)`。
- **尺寸规则依据有限**：docstring 称尺寸需为 16 的倍数（如 16:9 1080p 用 1920x1088），来源 'pucoding.com Image API' 为注释性来源，实际服务端接受的尺寸集合无法从代码确定；21:9 只有 2 档，档位越界钳到最后档。
- **兼容端点差异**：OpenAI 兼容端点是否支持/忽略额外参数（如 quality:'auto'）取决于具体网关实现，代码不可知。
- **归档失败兜底**：`archive_generated_image` 失败时删除半成品 `target.unlink(missing_ok=True)` 并返回原始 source 供调用方兜底；本地源不存在也直接返回 source。

## 迭代记录

| 日期 | 变更说明 |
|------|---------|
| 2026-09-19 | 初始创建 — harness-init 基于源码分析自动生成 |
| 2026-09-19 | 自校修订 — 核实消费方链路（script_workflow.py:675-742 / storyboard.py:555-576，同函数内复用实例）；修正回写描述：定妆照走 update_lookbook（lookbook_images）、素材图走 update_episode_material（episode_material_images），状态流转补全 pending→processing→completed/failed；补充 script_manager.py 路径；删除对临时扫描文件的引用；精确化 b64 落盘相对路径与 resolve_project_path 锚定差异的表述 |
| 2026-09-21 | 状态机统一 — 新增 ImageTaskService（image_task_service.py，131 行）收敛三处生图状态机：依赖注入与持久层解耦（image_service 参数 + update_row 回调适配两类表 + on_completed/interrupt/pre_update/label）；run_batch（IMAGE_REQUEST_TIME_GAP 间隔限流 + gather 并发轮询，单张失败不中断）/ run_single（失败标 failed 并抛 WorkflowError）；消费点更新为 script_workflow.py:708/:733、storyboard.py:503；术语「定妆照」→「核心素材图」；prompt 模板中文化（130-220 中文字、人物三视图/场景全景）；素材库配套（list_completed_lookbooks / insert_lookbook(image_path, meta) / delete_script_data(keep_completed_lookbooks) + lookbook_library_service.py） |
