# Harness Index — 项目知识总索引

> 最后更新: 2026-09-19

---

## Features & Logics — 功能与逻辑

功能需求到代码位置的映射，以及核心逻辑流程文档。

| 类型 | 名称 | 文档 | 核心路径 / 描述 |
|------|------|------|----------------|
| feature | Agent 异步运行框架 | [features/agent-run-framework.md](featuresAndLogics/features/agent-run-framework.md) | backend/core/agent_sdk/registry.py, backend/api/v1/agent_runs.py
| feature | 剧本实体库管理 | [features/entity-management.md](featuresAndLogics/features/entity-management.md) | backend/api/v1/script_sessions.py, /api/v1/script-sessions/{session_id}/entities
| feature | 前端公共设施 | [features/frontend-common.md](featuresAndLogics/features/frontend-common.md) | frontend/src/components/common/SessionSider.tsx, frontend/src/components/layout/MainLayout.tsx
| feature | 前端剧本工作台 | [features/frontend-script-workbench.md](featuresAndLogics/features/frontend-script-workbench.md) | frontend/src/pages/ScriptWorkflowPage.tsx, frontend/src/components/script/StepIdeationChat.tsx
| feature | 前端视频工作台（WorkflowPage 4 步向导） | [features/frontend-video-workbench.md](featuresAndLogics/features/frontend-video-workbench.md) | frontend/src/pages/WorkflowPage.tsx, frontend/src/components/workflow/StepNavigator.tsx
| feature | 剧本定妆照生成 | [features/lookbook-generation.md](featuresAndLogics/features/lookbook-generation.md) | backend/api/v1/script_sessions.py, _require_default_image_model
| feature | 模型配置管理 | [features/model-management.md](featuresAndLogics/features/model-management.md) | backend/api/v1/models.py, /api/v1/models
| feature | 提示词管理 | [features/prompt-management.md](featuresAndLogics/features/prompt-management.md) | backend/core/services/prompt_manager.py, PromptManager
| feature | 剧本创作工作流 | [features/script-workflow.md](featuresAndLogics/features/script-workflow.md) | backend/api/v1/script_sessions.py, /api/v1/script-sessions
| feature | 分镜工作流 | [features/storyboard-workflow.md](featuresAndLogics/features/storyboard-workflow.md) | backend/core/agents/storyboard.py, StoryboardWorkflow
| feature | 文件上传与会话资产管理 | [features/upload-and-assets.md](featuresAndLogics/features/upload-and-assets.md) | backend/api/v1/_upload.py, UPLOAD_ROOT = static/uploads
| feature | 视频创作工作流（视频会话与生成） | [features/video-workflow.md](featuresAndLogics/features/video-workflow.md) | backend/api/v1/sessions.py, backend/api/v1/steps.py
| logic | Claude Agent SDK 封装逻辑 | [logics/agent-sdk-wrapper.md](featuresAndLogics/logics/agent-sdk-wrapper.md) | ClaudeSDKClient 消息流归一为 AgentEvent，支持多轮 resume、inte
| logic | ComfyUI 时间轴视频生成逻辑 | [logics/comfyui-video-generation.md](featuresAndLogics/logics/comfyui-video-generation.md) | 构建 5+17n 帧对齐 timeline 注入 ComfyUI 生成长视频，默认 mock 兜底
| logic | 双层持久化与投影逻辑 | [logics/dual-persistence-projection.md](featuresAndLogics/logics/dual-persistence-projection.md) | workspace 文件为权威源、SQLite 只存薄 envelope，投影层还原旧 step_r
| logic | OpenAI 兼容生图服务 | [logics/image-generation-service.md](featuresAndLogics/logics/image-generation-service.md) | OpenAI 兼容生图：配置校验、文生图/图生图、重试退避、同步结果缓存
| logic | 进程内 MCP 写侧工具逻辑 | [logics/mcp-tool-writing.md](featuresAndLogics/logics/mcp-tool-writing.md) | script_design MCP 五写工具，save_episode 强校验失败自纠重试
| logic | Agent 模型端点环境注入逻辑 | [logics/model-env-injection.md](featuresAndLogics/logics/model-env-injection.md) | build_agent_env 从 SQLite image_models 读 agent 默认模型
| logic | 剧本上下文装配逻辑 | [logics/script-context-assembly.md](featuresAndLogics/logics/script-context-assembly.md) | ScriptContextService 从工作区 markdown 装配分镜上下文（分集设计/实体
| logic | 会话步骤状态机逻辑 | [logics/session-step-state-machine.md](featuresAndLogics/logics/session-step-state-machine.md) | 两条 4 步工作流以 SQLite step_results 的 _success 标志驱动线性推进
| logic | SSE 事件流协议逻辑 | [logics/sse-event-stream.md](featuresAndLogics/logics/sse-event-stream.md) | SSE 按 seq 增量推送 AgentRun 事件，支持断线重连续传与取消
| logic | 文件化工作区存储逻辑 | [logics/workspace-store.md](featuresAndLogics/logics/workspace-store.md) | WorkspaceStore 以 markdown+frontmatter 文件树作为剧本/分镜产物

→ 详见 [featuresAndLogics/features/index.md](featuresAndLogics/features/index.md)
→ 详见 [featuresAndLogics/logics/index.md](featuresAndLogics/logics/index.md)

---

## Learned — 经验教训

开发过程中踩过的坑、关键问题的解决方案。

| 名称 | 文件 | tags |
|------|------|------|
| - | - | - |

→ 详见 [learned/index.md](learned/index.md)（初始为空，经 /harness-update 补充）

---

## Project Rules — 项目规范

开发门禁、编码规范、实现规范、技术规范、字段规范。

| 名称 | 文件 | 类别 |
|------|------|------|
| api-and-sse-conventions | [project-rules/api-and-sse-conventions.md](api-and-sse-conventions.md) | 实现规范
| id-and-path-safety | [project-rules/id-and-path-safety.md](id-and-path-safety.md) | 门禁
| model-config-conventions | [project-rules/model-config-conventions.md](model-config-conventions.md) | 实现规范
| workspace-authoritative-storage | [project-rules/workspace-authoritative-storage.md](workspace-authoritative-storage.md) | 实现规范

→ 详见 [project-rules/index.md](project-rules/index.md)

---

project-context.md — 项目上下文，单一文件无需索引。

## 快速参考

| 目录 | 用途 | 文件命名 |
|------|------|---------|
| `featuresAndLogics/features/` | 功能→代码映射 | `{feature-name}.md` |
| `featuresAndLogics/logics/` | 核心逻辑文档 | `{logic-name}.md` |
| `learned/` | 经验教训 | `{topic-name}.md` |
| `project-context.md` | 项目方向性知识（目标、架构、设计原则、核心约束） | - |
| `project-rules/` | 项目规范（门禁、编码规范） | `{rule-name}.md` |
| `project-config.yaml` | 挂链查询清单（数据库/中间件/关联仓库） | - |

> 所有文件名使用 kebab-case。非 index 文件必须有 frontmatter: name, 摘要, tags。

---
*由 harness-init 创建于 2026-09-19，索引重建于 2026-09-19*
