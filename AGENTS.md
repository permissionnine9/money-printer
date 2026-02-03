# AI视频创作智能体 - 项目指南

本文件为AI编程助手提供项目背景、架构说明和开发指南。
/src 是重构前的前后端耦合的代码
/backend和/frontend是重构后的代码

## 项目概述

本项目是一个基于多轮独立架构的AI视频创作智能体，支持从脚本到视频的全流程自动化。项目采用6步工作流，每个步骤完全解耦，支持中断和恢复。

**核心目标**: 基于用户输入的长脚本，通过LLM优化、生成素材图、分镜切片、生成首尾帧，最终使用即梦或wan2.2生成视频片段。

**项目语言**: 中文（注释和文档主要使用中文）

## 技术栈

| 组件 | 技术 |
|------|------|
| **Agent框架** | LangGraph |
| **LLM** | 豆包 Seed 1.8 (`bytedance/doubao-seed-1.8`) |
| **图片生成(文生图)** | GPT Image 1.5 (`openai/gpt-image-1.5`) |
| **图片生成(图生图)** | Gemini 2.5 Flash Image (`google/gemini-2.5-flash-image`) |
| **素材图生成** | Gemini 3 Pro Image Preview (`google/gemini-3-pro-image-preview`) |
| **视频生成** | 即梦首尾帧 (`bytedance/jimeng_i2v_first_tail_v30`) 或 阿里wan2.2 (`ali/wan2.2-kf2v-flash`) |
| **前端界面** | Gradio 5.x / React 18 + TypeScript + Vite + Ant Design |
| **后端API** | FastAPI |
| **数据库** | SQLite（会话持久化） |
| **对象存储** | 阿里云 OSS（可选，用于视频服务） |
| **包管理** | UV |
| **Python版本** | >= 3.11 |

## 项目结构

```
money-print/
├── app_v2_improved.py          # 主入口：Gradio前端界面（V2改进版，推荐使用）
├── app.py                      # 旧版本入口（已弃用）
├── pyproject.toml              # 项目配置和依赖（使用UV管理）
├── .env.example                # 环境变量模板
├── .env                        # 实际环境变量（需手动创建）
│
├── src/                        # 重构前的源代码目录（前后端耦合在一起）
│   ├── config.py               # 全局配置（API密钥、模型参数、选项等）
│   │
│   ├── models/                 # 数据模型（Pydantic）
│   │   └── video_models.py     # 视频创作相关模型
│   │
│   ├── services/               # 服务层
│   │   ├── llm_service.py      # LLM服务（脚本优化、分片切割）
│   │   ├── image_service.py    # 图片生成服务（文生图、图生图）
│   │   ├── video_service.py    # 视频生成服务（即梦）
│   │   ├── video_service_wan22.py  # 视频生成服务（wan2.2）
│   │   └── oss_service.py      # 阿里云OSS服务
│   │
│   ├── agents/                 # Agent模块
│   │   └── workflow_v2.py      # 视频创作工作流V2（6步流程）
│   │
│   ├── persistence/            # 持久化层
│   │   └── session_manager.py  # 会话状态管理（SQLite）
│   │
│   └── utils/                  # 工具模块
│       └── json_parser.py      # JSON解析工具
│
├── backend/                    # FastAPI后端API（前后端分离架构）
│   ├── main.py                 # FastAPI应用入口
│   ├── deps.py                 # 依赖注入
│   ├── api/v1/                 # API路由
│   │   ├── sessions.py         # 会话管理API
│   │   ├── steps.py            # 工作流步骤API
│   │   ├── segments.py         # 分片编辑API
│   │   ├── frames.py           # 首尾帧管理API
│   │   ├── materials.py        # 素材图管理API
│   │   └── uploads.py          # 文件上传API
│   └── schemas/                # Pydantic请求/响应模型
│
├── frontend/                   # React前端（Vite + TypeScript + Ant Design）
│   ├── src/
│   │   ├── api/                # API客户端（Axios封装）
│   │   ├── stores/             # Zustand状态管理
│   │   ├── hooks/              # 自定义Hooks
│   │   ├── components/         # UI组件
│   │   ├── types/              # TypeScript类型定义
│   │   └── App.tsx             # 主应用
│   ├── package.json            # npm依赖
│   └── vite.config.ts          # Vite配置
│
├── static/                     # 静态文件存储
│   ├── images/                 # 生成的图片
│   └── videos/                 # 生成的视频
│
├── data/                       # 数据存储
│   └── sessions.db             # SQLite会话数据库
│
├── templates/                  # HTML模板（预留）
│
├── build/                      # 构建输出目录
│
├── start_backend.sh            # 后端启动脚本
├── start_frontend.sh           # 前端启动脚本
│
└── 文档文件
    ├── readme.md               # 项目README
    ├── CLAUDE.md               # Claude Code指南
    ├── FASTAPI_README.md       # FastAPI后端文档
    ├── prd.md                  # 产品需求文档
    ├── UPGRADE.md              # 架构升级说明
    ├── api-shengsuanyun.md     # 盛算云API文档
    ├── api-jimeng.md           # 即梦API文档
    └── api-wan2.2.md           # wan2.2 API文档
```

## 工作流程（6步）

项目严格遵循PRD定义的6步流程：

1. **submit_script_and_params**: 用户提交脚本和视频参数（分辨率、宽高比、语言、风格、视角）
2. **optimize_script**: LLM优化总脚本，丰富细节
3. **generate_material_images**: 生成素材图（设定稿风格：角色、物品、场景）
4. **generate_segment_scripts**: LLM将脚本切分为8秒以内的分片
5. **generate_segment_frames**: 基于素材图生成分片的首尾帧
6. **generate_videos**: 使用首尾帧生成视频片段

## 快速开始

### 环境准备

```bash
# 1. 安装UV（如果未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 安装依赖（使用清华镜像加速）
uv sync

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填写必要的API密钥
```

### 启动应用

**方式一：使用Gradio版本（单文件运行）**
```bash
uv run python app_v2_improved.py
# 应用将在 http://localhost:7860 启动
```

**方式二：使用前后端分离架构**
```bash
# 启动后端（FastAPI）
./start_backend.sh
# 或: uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 启动前端（React）
./start_frontend.sh
# 或: cd frontend && npm run dev

# 前端: http://localhost:5173
# 后端API: http://localhost:8000
# API文档: http://localhost:8000/docs
```

## 环境变量配置

必需的环境变量（在 `.env` 文件中配置）：

```bash
# 盛算云 API Key（必需，用于LLM、图片生成、视频生成）
VERTEX_API_KEY=your_api_key_here
# 或
SHENGSUANYUN_API_KEY=your_api_key_here

# 视频服务类型切换
VIDEO_SERVICE_TYPE=jimeng  # 可选: "jimeng" 或 "wan22"

# 阿里云 OSS 配置（如果使用wan2.2视频服务）
OSS_ACCESS_KEY=your_oss_access_key
OSS_SECRET_KEY=your_oss_secret_key
OSS_BUCKET=your_bucket_name
```

## 核心模块详解

### 1. 工作流引擎 (`src/agents/workflow_v2.py`)

`VideoCreationWorkflowV2` 类编排整个6步工作流：

- 每个步骤有独立的方法：`step_submit`, `step_optimize_script`, `step_generate_material_images` 等
- 步骤执行前检查前置条件（`session_manager.can_execute_step`）
- 支持分片编辑、首尾帧管理等功能

### 2. 会话管理 (`src/persistence/session_manager.py`)

`SessionManager` 负责状态持久化：

- SQLite数据库存储会话状态和步骤结果
- `step_results` 表存储每个步骤的JSON结果
- 支持查询会话进度、已完成步骤列表
- 提供分片编辑、帧更新等数据操作接口

**数据库表结构**:
- `sessions`: 会话元信息（session_id, created_at, updated_at, current_step, status）
- `step_results`: 步骤结果（session_id, step_name, result_data, completed_at）

### 3. 服务层 (`src/services/`)

| 服务 | 职责 | 关键模型 |
|------|------|----------|
| LLMService | 脚本优化、分片切割、提示词生成 | `bytedance/doubao-seed-1.8` |
| ImageService | 素材图生成（文生图/图生图） | `openai/gpt-image-1.5`, `google/gemini-2.5-flash-image` |
| VideoService | 视频生成（即梦首尾帧） | `bytedance/jimeng_i2v_first_tail_v30` |
| VideoServiceWan22 | 视频生成（wan2.2首尾帧） | `ali/wan2.2-kf2v-flash` |
| OSSService | 阿里云OSS文件上传 | - |

### 4. 数据模型 (`src/models/video_models.py`)

核心Pydantic模型：

- `VideoParams`: 视频参数（分辨率、宽高比、语言、风格、视角）
- `ScriptSegment`: 分片脚本（内容、时长、动作、镜头运动、构图、氛围等）
- `MaterialImage`: 素材图（图片路径、任务ID、状态）
- `SegmentFrame`: 首尾帧（首帧/尾帧路径、提示词）
- `GeneratedVideo`: 生成的视频（视频路径、任务ID、状态）

### 5. FastAPI后端 (`backend/`)

RESTful API设计，支持前后端分离：

- **会话管理**: `POST /api/v1/sessions`, `GET /api/v1/sessions/{id}`
- **工作流步骤**: `POST /api/v1/steps/{session_id}/optimize` 等
- **分片编辑**: `PUT /api/v1/segments/{session_id}/{index}`
- **首尾帧管理**: `POST /api/v1/frames/{session_id}/{index}/regenerate`
- **文件上传**: `POST /api/v1/uploads/image`

## API配置说明

项目使用**盛算云**提供的API（兼容Google Gemini/OpenAI格式）：

- **API文档**: https://docs.router.shengsuanyun.com/353574235e0
- **Base URL**: `https://router.shengsuanyun.com/api/v1`

**关键配置**（在 `src/config.py` 中）：

```python
# 视频服务切换
VIDEO_SERVICE_TYPE = "jimeng"  # 或 "wan22"

# 模型配置
SHENGSUANYUN_VIDEO_MODEL = "bytedance/jimeng_i2v_first_tail_v30"
SHENGSUANYUN_VIDEO_MODEL_WAN22 = "ali/wan2.2-kf2v-flash"
SHENGSUANYUN_IMAGE_MODEL = "openai/gpt-image-1.5"
SHENGSUANYUN_IMAGE2IMAGE_MODEL = "google/gemini-2.5-flash-image"
```

## 开发规范

### 代码风格

- **语言**: Python 3.11+
- **类型注解**: 推荐使用类型提示
- **文档字符串**: 使用中文文档字符串说明函数功能
- **日志**: 使用 `logging` 模块，日志级别使用 INFO/ERROR/WARNING

### 添加新步骤

如需添加或修改工作流步骤，需同步更新以下位置：

1. `SessionManager.STEPS` 列表（`src/persistence/session_manager.py`）
2. `VideoCreationWorkflowV2` 的步骤方法（`src/agents/workflow_v2.py`）
3. `app_v2_improved.py` 的 `STEPS` 列表和UI组件
4. `get_step_component_visibility` 函数（控制组件可见性）

### 数据持久化规范

- 所有步骤结果**必须**通过 `session_manager.save_step_result()` 保存
- 步骤失败时设置 `success=False`，使 `current_step` 不前进，允许用户重试
- 异步任务（图片/视频生成）需要轮询任务状态直到完成

### 错误处理

```python
try:
    result = await some_async_operation()
    # 保存成功结果
    self.session_manager.save_step_result(session_id, step_name, result_data)
    return {"success": True, "data": result_data}
except Exception as e:
    logger.error(f"步骤失败: {str(e)}")
    # 保存失败状态，不推进current_step
    return {"success": False, "error": str(e)}
```

## 测试

项目目前没有自动化测试套件。建议的测试方式：

1. **功能测试**: 通过Gradio界面逐步验证每个功能
2. **API测试**: 使用 `api-*.md` 文档中的curl命令测试各API
3. **会话恢复测试**: 在中断后重新启动应用，验证能否恢复会话
4. **完整工作流测试**: `uv run python test_workflow_complete.py`

## 文件存储约定

| 类型 | 存储路径 |
|------|----------|
| 生成的图片 | `static/images/` |
| 生成的视频 | `static/videos/` |
| 会话数据库 | `data/sessions.db` |
| 日志文件 | `app_v2_improved.log` |

## 关键实现细节

### 即梦视频生成参数

```python
{
    "image_urls": [首帧URL, 尾帧URL],  # 首尾帧控制
    "frames": 121,  # 121=5秒，241=10秒
    "aspect_ratio": "16:9",  # 支持 16:9, 9:16, 1:1, 3:4, 4:3, 21:9
}
```

### 素材图生成模式

1. **文生图模式**: 不提供参考图，使用 `gpt-image-1.5` 生成
2. **图生图模式**: 提供参考图，使用 `gemini-3-pro-image-preview` 基于参考图生成

### 首尾帧生成

- 基于素材图作为参考（图生图）
- 使用 `gemini-2.5-flash-image` 模型
- 确保角色/物品一致性
- 支持首尾帧复用模式（`reuse_prev` / `reuse_next`）

## 架构特点

### V2架构优势

相比旧版本（`app.py`），V2版本完全解决了耦合问题：

| 特性 | V1（旧） | V2（新） |
|------|---------|---------|
| 架构 | LangGraph + interrupt | 独立步骤 + 持久化 |
| 步骤执行 | 必须连续执行 | 可独立执行、中断恢复 |
| 状态管理 | 单一GraphState | 每步独立保存到SQLite |
| 灵活性 | 低（强耦合） | 高（完全解耦） |
| 人机交互 | 连续模式 | 每步确认后持久化 |

### 前后端分离架构

```
┌─────────────┐         HTTP/REST         ┌─────────────┐
│   React     │ ◄────────────────────────► │   FastAPI   │
│   前端      │     JSON 数据交换           │   后端      │
│  (5173)     │                            │   (8000)    │
└─────────────┘                            └─────────────┘
      │                                           │
   Zustand                                   SQLite DB
   状态管理                                   会话持久化
```

## 注意事项

1. **网络环境**: 视频生成需要较长时间（每个片段约1-2分钟），建议在稳定网络环境下使用
2. **API配额**: API调用可能产生费用，注意配额管理
3. **存储空间**: 生成的图片和视频会占用磁盘空间，定期清理 `static/` 目录
4. **Python版本**: 必须使用 Python 3.11+（依赖LangGraph 0.3+）

## 常见问题

### Q: 如何切换视频生成服务？
A: 修改 `.env` 文件中的 `VIDEO_SERVICE_TYPE` 为 `jimeng` 或 `wan22`，或修改 `src/config.py` 中的默认值。

### Q: 会话数据存储在哪里？
A: 会话数据存储在 `data/sessions.db` SQLite数据库中，可安全删除以重置所有会话。

### Q: 如何修改默认视频参数？
A: 修改 `src/config.py` 中的 `DEFAULT_VIDEO_PARAMS` 字典。

### Q: 如何添加新的API端点？
A: 
1. 在 `backend/schemas/` 中定义请求/响应模型
2. 在 `backend/api/v1/` 中实现路由
3. 在 `backend/main.py` 中注册路由
4. 在 `frontend/src/api/client.ts` 中添加客户端方法

## 参考文档

- [盛算云API文档](api-shengsuanyun.md)
- [即梦API文档](api-jimeng.md)
- [wan2.2 API文档](api-wan2.2.md)
- [产品需求文档](prd.md)
- [架构升级说明](UPGRADE.md)
- [FastAPI后端文档](FASTAPI_README.md)
