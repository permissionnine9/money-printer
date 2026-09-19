---
name: OpenAI 兼容生图服务
摘要: OpenAI 兼容生图：配置校验、文生图/图生图、重试退避、同步结果缓存
tags: 生图服务, OpenAI兼容, 图像压缩, 模型配置
---

# OpenAI 兼容生图服务

**最后更新:** 2026-09-19

## 逻辑概述

以 OpenAI Images API 兼容协议访问第三方生图端点（文生图 `POST {base_url}/images/generations`，图生图 `POST {base_url}/images/edits`），核心要点：

- **配置驱动，无内置默认端点**：`build_image_service_from_model_config` 经 ModelManager 读取 SQLite `image_models` 表，逐项校验 api_key / base_url / model_id，任一缺失即报错；未配置 model_config_id 时取 `model_type='image'` 的默认模型。
- **同步生成协议**：submit 时即完成 HTTP 请求并解析结果，写入实例级内存缓存 `_sync_results`（`dict[str,str]`）；`poll_i2i_task` 仅从缓存 pop 取回（`timeout`/`poll_interval` 参数未使用，保留签名兼容调用方）。
- **尺寸硬编码查表**：`_get_openai_image_size` 按 aspect_ratio × resolution 查表，未知 aspect_ratio 回退 16:9，未知 resolution 回退 720p 档，档位越界钳到最后档。
- **有限重试**：max_attempts=3，仅对 404/429/500/502/503 重试，线性退避 5s/10s；错误文本截断 300 字符。
- **参考图可选压缩**：图生图硬上限 4 张，压缩走 PIL（白底转 RGB、LANCZOS 缩放到最长边 1920、JPEG quality=85）。
- **落盘与归档分离**：b64 结果落盘 `static/images/`，再由 `archive_generated_image` 归档到 `static/images/{story}/{episode}/`，经 `backend/main.py` 的 `app.mount('/static')` 对外暴露。

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
10. 消费与回写状态（已核实）— 两处消费方均在同一函数内 build→submit→poll 复用同一 ImageService 实例：
    - 定妆照：`backend/core/agents/script_workflow.py` — 批量生成 `build_image_service_from_model_config(model_config_id)`（:675）→ 逐张 `submit_image_task(row['prompt'], LOOKBOOK_VIDEO_PARAMS, None)`（:690）→ `poll_i2i_task(request_id, timeout=180, poll_interval=5)`（:702），结果经 `self.scm.update_lookbook(image_id, {...})` 回写 `lookbook_images` 表；单张重试链路在 :731-742（重建服务→submit→poll→回写）。
    - 分集素材图：`backend/core/agents/storyboard.py` — `build_image_service_from_model_config(model_config_id)`（:555）→ `submit_image_task(image_prompt, video_params, gen_refs or None)`（:558）→ `poll_i2i_task(submit['request_id'])`（:563）→ `archive_generated_image`（:576），结果经 `scm.update_episode_material(mat_id, {...})` 回写 `episode_material_images` 表。
    - 状态机流转（ScriptManager，backend/core/persistence/script_manager.py）：pending → processing（登记 task_id）→ completed（写 image_path）/ failed（提交或轮询失败均置 failed）。

## 涉及代码

- `backend/core/services/image_service.py` — 核心实现：常量 IMAGE_COMPRESS_MAX_SIZE=1920 / IMAGE_COMPRESS_QUALITY=85、`ImageModelNotConfiguredError`、工厂 `build_image_service_from_model_config`、`ImageService`（构造、`_get_openai_image_size` 尺寸表、`submit_image_task`、`_submit_openai_image_task`、`_load_reference_bytes`、`poll_i2i_task`、`_sync_results` 缓存）。
- `backend/core/utils/image_utils.py` — 辅助实现：`compress_image(image_data, max_size, quality) -> (bytes, mime)`、`load_image_bytes(image_path, compress=False, *, max_size=1920, quality=85) -> (bytes|None, mime|None)`。
- `backend/core/utils/image_store.py` — 归档实现：`_INVALID_CHARS` 正则、`sanitize_name`、`_guess_ext`、`archive_generated_image`。
- `backend/core/utils/path_utils.py` — `resolve_project_path` 锚定项目根；IMAGE_SAVE_DIR（=Path('static/images')）/VIDEO_SAVE_DIR/PROJECT_ROOT 定义于此。
- `backend/core/persistence/model_manager.py` — ModelManager（SQLite image_models 表，模型配置读取）。
- `backend/core/persistence/script_manager.py` — ScriptManager：lookbook_images / episode_material_images 表及 update_lookbook / update_episode_material 回写。
- `backend/main.py` — `app.mount('/static')` 静态对外暴露生成图片。
- `backend/core/agents/script_workflow.py`（:675-742）、`backend/core/agents/storyboard.py`（:555-576）— 消费方（定妆照 / 分集素材图），已逐行核实。

## 相关功能

- 模型管理（image_models 表：默认 image 模型配置、api_key/base_url/model_id）
- 定妆照 / 分集素材图生成（script_workflow.py、storyboard.py 调用方链路）
- 静态资源服务（/static 挂载，生成图片对外访问）

## 注意事项

- **未配置兜底**：submit 前置校验返回统一文案 `_NOT_CONFIGURED_MSG`；工厂层面无默认配置报'未配置默认生图模型...'，指定 id 不存在抛 `ImageModelNotConfiguredError`。无内置默认端点。
- **缓存生命周期**：`_sync_results` 是实例级内存缓存，跨 ImageService 实例/进程重启即失效。已核实两个消费方（script_workflow.py、storyboard.py）均在同一函数内 build→submit→poll 复用同一实例，缓存命中无跨实例风险；但若调用方在 submit 与 poll 之间重建服务（如跨请求轮询）则会得到'任务结果不存在'。
- **poll 参数为空壳**：`timeout=150`/`poll_interval=3` 未使用（script_workflow.py 调用时传 timeout=180, poll_interval=5 同样无效）；OpenAI 协议同步生成，submit 时结果已缓存，'任务结果不存在'可能表示已被取回或提交失败。
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
