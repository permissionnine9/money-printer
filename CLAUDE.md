# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AI视频创作智能体 - 基于LangGraph的视频生成工作流，支持从脚本到视频的全流程自动化。

**核心目标**: 基于用户输入的长脚本，通过LLM优化、生成素材图、分镜切片、生成首尾帧，最终使用即梦生成视频片段。

## 常用命令

### 环境管理
```bash
# 安装依赖（使用清华镜像）
uv sync

# 启动应用（V2版本，推荐）
uv run python app_v2_improved.py

# 启动旧版本
uv run python app.py
```

### 测试
```bash
# 测试架构核心功能（不依赖API）
uv run python test_architecture.py

# 测试完整工作流（需要API）
uv run python test_workflow_v2.py
```

### 环境配置
```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，配置 VERTEX_API_KEY
# API密钥格式：AIza... 开头的39字符字符串
```

## 技术栈

- **Agent框架**: LangGraph
- **LLM**: Google Gemini 2.0 Flash (`gemini-2.5-flash`)
- **图片生成**: Nano Banana Pro (`gemini-3-pro-image-preview`)
- **视频生成**: 即梦 (`bytedance/jimeng_i2v_first_tail_v30`，支持首尾帧控制)
- **前端界面**: Gradio
- **包管理**: UV
- **数据库**: SQLite（会话持久化）

## 架构设计

### 核心工作流程（6步，符合PRD）

项目采用**多轮独立架构**，每个步骤完全解耦，支持中断和恢复：

1. **submit_script_and_params**: 用户提交脚本和视频参数（分辨率、宽高比、语言、风格、视角）
2. **optimize_script**: LLM优化脚本，丰富细节，设计8秒以内的转场分片
3. **generate_material_images**: 生成"设定稿"风格的素材图（2-3张）：
   - **角色设定图**：所有角色的多角度展示，带身高比例尺
   - **物品设定图**：重要道具/物品，带尺寸标注
   - **场景设定图**：主要场景的概览（如需要）
4. **generate_segment_scripts**: LLM生成分镜头切片脚本，保持与总脚本的连贯性
5. **generate_segment_frames**: 基于素材图（图生图），生成每个分片的首尾帧，确保角色/物品一致性
6. **generate_videos**: 使用即梦基于首尾帧生成视频片段

### 关键设计原则

- **完全解耦**: 每个步骤独立执行，互不耦合
- **自动持久化**: 每步完成后立即保存到SQLite数据库（`data/sessions.db`）
- **会话恢复**: 应用启动时自动加载最近的活动会话，支持从任意步骤继续
- **人机交互**: 每个步骤都支持人工审核确认，可以编辑分片脚本、删除/重新生成首尾帧

### 核心模块

#### 1. 工作流引擎 (`src/agents/workflow_v2.py`)

`VideoCreationWorkflowV2` 类负责编排整个工作流：

- 每个步骤都有独立的方法（如 `step_submit`, `step_optimize_script`, `step_generate_material_images` 等）
- 步骤执行前会检查前置步骤是否完成（`can_execute_step`）
- 支持分片脚本编辑、首尾帧管理等辅助功能

#### 2. 会话管理 (`src/persistence/session_manager.py`)

`SessionManager` 类负责状态持久化：

- 使用SQLite存储会话状态和步骤结果
- 每个步骤的结果以JSON格式存储在 `step_results` 表中
- 支持查询会话进度、已完成步骤列表、步骤结果等
- 提供分片编辑、帧更新等数据操作接口

数据库表结构：
- `sessions`: 存储会话元信息（session_id, created_at, updated_at, current_step, status）
- `step_results`: 存储每个步骤的结果（session_id, step_name, result_data, completed_at）

#### 3. 服务层 (`src/services/`)

- **LLMService** (`llm_service.py`): 使用Gemini 2.5 Flash进行脚本优化、分片切割、提示词生成
- **ImageService** (`image_service.py`):
  - 素材图生成：使用文生图模型 (`openai/gpt-image-1.5`)
  - 首尾帧生成：使用图生图模型 (`google/gemini-2.5-flash-image`)，以素材图作为参考，确保角色/物品一致性
- **VideoService**: 视频生成服务，支持两种后端：
  - `video_service.py` (即梦): 使用 `bytedance/jimeng_i2v_first_tail_v30`，参数 `image_urls: [首帧, 尾帧]`
  - `video_service_wan22.py` (wan2.2): 使用 `ali/wan2.2-kf2v-flash`，参数 `first_frame_url`, `last_frame_url`
  - 通过环境变量 `VIDEO_SERVICE_TYPE` 切换（`jimeng` 或 `wan22`）

#### 4. 数据模型 (`src/models/video_models.py`)

使用Pydantic定义所有数据结构：
- `VideoParams`: 视频参数（分辨率、宽高比、语言、风格、视角）
- `ScriptSegment`: 分片脚本（内容、时长、动作、镜头运动、构图、氛围等）
- `MaterialImage`: 素材图（图片路径、任务ID、状态、描述）
- `SegmentFrame`: 首尾帧（首帧/尾帧路径、提示词）
- `GeneratedVideo`: 生成的视频（视频路径、任务ID、状态）

### 前端界面 (`app_v2_improved.py`)

使用Gradio构建：

- **步骤导航**: 6个步骤按钮，点击可查看各步骤的详细结果
- **参数输入**: 步骤1时可编辑脚本和参数，完成后自动锁定
- **动态显示**: 根据当前步骤显示对应的输出（脚本、图片、视频）
- **分片编辑**: 使用 `@gr.render` 动态渲染分片编辑表单，支持保存、删除、新增
- **首尾帧管理**: 支持上传替换或重新生成首尾帧
- **会话恢复**: 启动时自动加载最近的活动会话

## API配置

项目使用盛算云提供的API（兼容Google Gemini格式）：

- API文档: https://docs.router.shengsuanyun.com/353574235e0
- 配置位置: `src/config.py`
- 环境变量: `VERTEX_API_KEY`（必需）

关键配置：
```python
SHENGSUANYUN_BASE_URL = "https://router.shengsuanyun.com/api/v1"

# 视频服务切换
VIDEO_SERVICE_TYPE = "jimeng"  # 可选: "jimeng" 或 "wan22"

# 视频模型
SHENGSUANYUN_VIDEO_MODEL = "bytedance/jimeng_i2v_first_tail_v30"  # 即梦首尾帧
SHENGSUANYUN_VIDEO_MODEL_WAN22 = "ali/wan2.2-kf2v-flash"  # wan2.2首尾帧

# 图片模型
SHENGSUANYUN_IMAGE_MODEL = "openai/gpt-image-1.5"
```

## 重要注意事项

### 开发建议

1. **修改工作流步骤**: 如需添加或修改步骤，需同步更新以下位置：
   - `SessionManager.STEPS` 列表
   - `VideoCreationWorkflowV2` 的步骤方法
   - `app_v2_improved.py` 的 `STEPS` 列表和UI组件
   - `get_step_component_visibility` 函数（控制组件可见性）

2. **数据持久化**: 所有步骤的结果必须通过 `session_manager.save_step_result()` 保存，确保可以恢复会话

3. **错误处理**: 步骤失败时需在 `save_step_result` 中设置 `success=False`，这样 `current_step` 不会前进，允许用户修复问题后重试

4. **异步操作**: 图片和视频生成是异步的，需要轮询任务状态直到完成（参考 `ImageService.poll_task` 和 `VideoService.poll_video_task`）

5.  即梦首尾帧 API 参数：
    - `image_urls`: 图片URL数组 `[首帧URL, 尾帧URL]`
    - `frames`: 视频帧数（121=5秒，241=10秒）
    - `aspect_ratio`: 宽高比（16:9, 4:3, 1:1, 3:4, 9:16, 21:9）

### 文件存储

- 生成的图片保存在: `static/images/`
- 生成的视频保存在: `static/videos/`
- 会话数据库位置: `data/sessions.db`
- 日志文件: `app_v2_improved.log`

### 依赖镜像

项目配置了清华大学PyPI镜像（`pyproject.toml` 中的 `[tool.uv]` 配置），确保在中国大陆环境下依赖安装速度。

### V2架构优势

相比旧版本（`app.py`），V2版本完全解决了耦合问题：
- V1: 所有步骤耦合在一起，中断后无法恢复
- V2: 每个步骤独立执行，支持中断和恢复，易于维护和扩展

详细说明请查看 `UPGRADE.md`。
