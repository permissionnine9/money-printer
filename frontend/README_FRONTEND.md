# FastAPI + React 前端重构

## 快速开始

### 1. 启动后端

```bash
# 在项目根目录
uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

后端将在 http://localhost:8000 启动，API 文档可访问 http://localhost:8000/docs

### 2. 启动前端

```bash
# 进入 frontend 目录
cd frontend

# 启动开发服务器
npm run dev
```

前端将在 http://localhost:5173 启动

## 项目结构

### 后端 (backend/)

- `main.py`: FastAPI 应用入口
- `deps.py`: 依赖注入
- `api/v1/`: API 路由
  - `sessions.py`: 会话管理 API
  - `steps.py`: 6 个工作流步骤 API
  - `segments.py`: 分片编辑 API
  - `frames.py`: 首尾帧管理 API
  - `materials.py`: 素材图管理 API
  - `uploads.py`: 文件上传 API
- `schemas/`: 请求/响应模型

### 前端 (frontend/)

- `src/api/`: API 客户端封装
- `src/stores/`: Zustand 状态管理
  - `sessionStore.ts`: 会话状态
  - `workflowStore.ts`: 工作流状态
- `src/hooks/`: 自定义 Hooks
  - `usePolling.ts`: 轮询 Hook
- `src/components/`: UI 组件
  - `layout/`: 布局组件
  - `workflow/`: 工作流组件
- `src/types/`: TypeScript 类型定义

## API 端点

### 会话管理
- `POST /api/v1/sessions` - 创建会话
- `GET /api/v1/sessions` - 获取会话列表
- `GET /api/v1/sessions/{id}` - 获取会话详情
- `DELETE /api/v1/sessions/{id}` - 删除会话

### 工作流步骤
- `POST /api/v1/steps/{session_id}/submit` - 步骤1：提交脚本
- `POST /api/v1/steps/{session_id}/optimize` - 步骤2：优化脚本
- `POST /api/v1/steps/{session_id}/materials` - 步骤3：生成素材图
- `POST /api/v1/steps/{session_id}/segments` - 步骤4：生成分片
- `POST /api/v1/steps/{session_id}/frames` - 步骤5：生成首尾帧
- `POST /api/v1/steps/{session_id}/videos` - 步骤6：生成视频

### 编辑操作
- `PUT /api/v1/segments/{session_id}/{index}` - 更新分片
- `DELETE /api/v1/segments/{session_id}/{index}` - 删除分片
- `POST /api/v1/frames/{session_id}/{segment_index}/regenerate` - 重新生成帧
- `POST /api/v1/frames/{session_id}/{segment_index}/upload` - 上传帧
- `POST /api/v1/materials/{session_id}/{index}/edit` - 编辑素材图
- `DELETE /api/v1/materials/{session_id}/{index}` - 删除素材图

### 文件上传
- `POST /api/v1/uploads/image` - 上传图片

## 特性

- ✅ 完整的 RESTful API
- ✅ 现代化 React + TypeScript 前端
- ✅ Ant Design 5.x UI 组件
- ✅ Zustand 轻量级状态管理
- ✅ 自动轮询任务状态
- ✅ 响应式设计
- ✅ 类型安全

## 下一步

目前已完成基础架构，包括：

1. ✅ 后端 API 完整实现
2. ✅ 前端基础搭建
3. ✅ API 客户端和状态管理
4. ✅ 主布局和步骤导航

待完成：

- 6 个工作流步骤的详细 UI 组件
- 分片编辑器组件
- 首尾帧管理组件
- 素材图管理组件
- 视频播放器组件

您可以继续开发各个步骤的 UI 组件，或者先测试当前的基础功能。
