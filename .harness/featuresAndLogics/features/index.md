# Features 功能索引

> 最后更新: 2026-09-19

| 名称 | 文件 | 状态 | 核心代码路径 | 迭代记录 | tags |
|------|------|------|------------|---------|------|
| Agent 异步运行框架 | [agent-run-framework.md](agent-run-framework.md) | 已完成 | backend/core/agent_sdk/registry.py, backend/api/v1/agent_runs.py | 2026-09-19 初始创建 | backend, sse, asyncio, agent-sdk, registry |
| 剧本实体库管理 | [entity-management.md](entity-management.md) | 已完成 | backend/api/v1/script_sessions.py, /api/v1/script-sessions/{session_id}/entities | 2026-09-19 初始创建 | 实体管理, 后端API, 文件化存储, Agent MCP, 前端组件 |
| 前端公共设施 | [frontend-common.md](frontend-common.md) | 已完成 | frontend/src/components/common/SessionSider.tsx, frontend/src/components/layout/MainLayout.tsx | 2026-09-19 初始创建 | 前端, 公共组件, hooks, SSE, API客户端 |
| 前端剧本工作台 | [frontend-script-workbench.md](frontend-script-workbench.md) | 已完成 | frontend/src/pages/ScriptWorkflowPage.tsx, frontend/src/components/script/StepIdeationChat.tsx | 2026-09-19 初始创建 | frontend, script-workflow, sse, polling, zustand |
| 前端视频工作台（WorkflowPage 4 步向导） | [frontend-video-workbench.md](frontend-video-workbench.md) | 已完成 | frontend/src/pages/WorkflowPage.tsx, frontend/src/components/workflow/StepNavigator.tsx | 2026-09-19 初始创建 | 前端, 视频工作流, 页面组件, zustand, 轮询, SSE |
| 剧本定妆照生成 | [lookbook-generation.md](lookbook-generation.md) | 已完成 | backend/api/v1/script_sessions.py, _require_default_image_model | 2026-09-19 初始创建 | 剧本工作流, 定妆照, 生图, AgentSDK, SQLite, 前端组件 |
| 模型配置管理 | [model-management.md](model-management.md) | 已完成 | backend/api/v1/models.py, /api/v1/models | 2026-09-19 初始创建 | 模型配置, 后端API, 前端页面, SQLite |
| 提示词管理 | [prompt-management.md](prompt-management.md) | 已完成 | backend/core/services/prompt_manager.py, PromptManager | 2026-09-19 初始创建 | 提示词模板, 后端API, 前端页面, Agent SDK, 文件存储 |
| 剧本创作工作流 | [script-workflow.md](script-workflow.md) | 已完成 | backend/api/v1/script_sessions.py, /api/v1/script-sessions | 2026-09-19 初始创建 | 剧本工作流, 后端API, 前端页面, AgentSDK, SSE, workspace文件化 |
| 分镜工作流 | [storyboard-workflow.md](storyboard-workflow.md) | 已完成 | backend/core/agents/storyboard.py, StoryboardWorkflow | 2026-09-19 初始创建 | 分镜, 视频工作流, AgentSDK, 文件化工作区, SSE |
| 文件上传与会话资产管理 | [upload-and-assets.md](upload-and-assets.md) | 已完成 | backend/api/v1/_upload.py, UPLOAD_ROOT = static/uploads | 2026-09-19 初始创建 | 文件上传, 后端API, 资产管理, SQLite, 静态文件 |
| 视频创作工作流（视频会话与生成） | [video-workflow.md](video-workflow.md) | 已完成 | backend/api/v1/sessions.py, backend/api/v1/steps.py | 2026-09-19 初始创建 | 后端API, 视频生成, ComfyUI, 会话管理, 前端页面 |
