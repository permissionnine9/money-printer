# Harness Index — 项目知识总索引

> 最后更新: 2026-09-21

---

## Features & Logics — 功能与逻辑

功能需求到代码位置的映射，以及核心逻辑流程文档。

| 类型 | 名称 | 文档 | 核心路径 / 描述 |
|------|------|------|----------------|
| feature | Agent 异步运行框架 | [features/agent-run-framework.md](featuresAndLogics/features/agent-run-framework.md) | backend/core/agent_sdk/registry.py, backend/api/v1/agent_runs.py — FIFO 排队（并发上限 5）+ SSE 观流 + 前端全局任务坞 |
| feature | 剧本实体库管理 | [features/entity-management.md](featuresAndLogics/features/entity-management.md) | backend/api/v1/script_sessions.py, /api/v1/script-sessions/{session_id}/entities |
| feature | 前端公共设施 | [features/frontend-common.md](featuresAndLogics/features/frontend-common.md) | frontend/src/components/common/SessionSider.tsx, frontend/src/components/layout/MainLayout.tsx — 全局任务坞 AgentRunDock |
| feature | 前端剧本工作台 | [features/frontend-script-workbench.md](featuresAndLogics/features/frontend-script-workbench.md) | frontend/src/pages/ScriptWorkflowPage.tsx, frontend/src/components/script/StepIdeationChat.tsx |
| feature | 前端视频工作台（WorkflowPage 4 步向导） | [features/frontend-video-workbench.md](featuresAndLogics/features/frontend-video-workbench.md) | frontend/src/pages/WorkflowPage.tsx, frontend/src/components/workflow/StepNavigator.tsx |
| feature | 剧本核心素材图生成 | [features/lookbook-generation.md](featuresAndLogics/features/lookbook-generation.md) | backend/api/v1/script_sessions.py, backend/core/services/image_task_service.py — 中文 prompt 三视图/全景 |
| feature | 核心素材图素材库 | [features/lookbook-library.md](featuresAndLogics/features/lookbook-library.md) | backend/core/services/lookbook_library_service.py — 跨剧本复用已完成核心素材图（复制导入/溯源/回滚） |
| feature | 模型配置管理 | [features/model-management.md](featuresAndLogics/features/model-management.md) | backend/api/v1/models.py, /api/v1/models |
| feature | 提示词管理 | [features/prompt-management.md](featuresAndLogics/features/prompt-management.md) | backend/core/services/prompt_manager.py, PromptManager |
| feature | 剧本创作工作流 | [features/script-workflow.md](featuresAndLogics/features/script-workflow.md) | backend/api/v1/script_sessions.py, backend/core/agents/script_workflow.py — adopt_story_logic/set_story_title |
| feature | 分镜工作流 | [features/storyboard-workflow.md](featuresAndLogics/features/storyboard-workflow.md) | backend/core/agents/storyboard.py, backend/core/services/material_pool_service.py — 参考图自动匹配/单分镜完成 |
| feature | 文件上传与会话资产管理 | [features/upload-and-assets.md](featuresAndLogics/features/upload-and-assets.md) | backend/api/v1/uploads.py — assets 路由已删除，落盘内联 uploads.py |
| feature | 视频创作工作流（视频会话与生成） | [features/video-workflow.md](featuresAndLogics/features/video-workflow.md) | backend/api/v1/sessions.py, backend/core/workflows/video_workflow.py — 指定段生成/备份恢复/导入到 ComfyUI |
| logic | Claude Agent SDK 封装逻辑 | [logics/agent-sdk-wrapper.md](featuresAndLogics/logics/agent-sdk-wrapper.md) | ClaudeSDKClient 消息流归一为 AgentEvent，支持多轮 resume、interrupt 取消；MAX_STREAM_BUFFER_SIZE=16MB |
| logic | ComfyUI 时间轴视频生成逻辑 | [logics/comfyui-video-generation.md](featuresAndLogics/logics/comfyui-video-generation.md) | 构建 5+17n 帧对齐 timeline 注入 ComfyUI 生成长视频，两段式导入/执行 + SSH 隧道部署，默认 mock 兜底 |
| logic | 双层持久化与投影逻辑 | [logics/dual-persistence-projection.md](featuresAndLogics/logics/dual-persistence-projection.md) | workspace 文件为唯一权威源、SQLite 只存薄 envelope，step_payload + workspace_sections 投影/装配 |
| logic | OpenAI 兼容生图服务 | [logics/image-generation-service.md](featuresAndLogics/logics/image-generation-service.md) | OpenAI 兼容生图 + ImageTaskService 统一三处生图任务状态机 |
| logic | 进程内 MCP 写侧工具逻辑 | [logics/mcp-tool-writing.md](featuresAndLogics/logics/mcp-tool-writing.md) | script_design MCP 五写工具，save_episode 强校验失败自纠重试 |
| logic | Agent 模型端点环境注入逻辑 | [logics/model-env-injection.md](featuresAndLogics/logics/model-env-injection.md) | build_agent_env 从 SQLite image_models 读 agent 默认模型 |
| logic | 剧本上下文装配逻辑 | [logics/script-context-assembly.md](featuresAndLogics/logics/script-context-assembly.md) | workspace_sections 共享装配段 + ScriptContextService 装配分镜上下文 + step_payload 投影读侧 |
| logic | 会话步骤状态机逻辑 | [logics/session-step-state-machine.md](featuresAndLogics/logics/session-step-state-machine.md) | 两条 4 步工作流以 SQLite step_results 的 _success 标志驱动线性推进 |
| logic | SSE 事件流协议逻辑 | [logics/sse-event-stream.md](featuresAndLogics/logics/sse-event-stream.md) | SSE 按 seq 增量推送 AgentRun 事件，断线重连续传、取消与并发排队 |
| logic | 文件化工作区存储逻辑 | [logics/workspace-store.md](featuresAndLogics/logics/workspace-store.md) | WorkspaceStore 以 markdown+frontmatter 文件树作为剧本/分镜产物权威源 |

→ 详见 [featuresAndLogics/features/index.md](featuresAndLogics/features/index.md)
→ 详见 [featuresAndLogics/logics/index.md](featuresAndLogics/logics/index.md)

---

## Learned — 经验教训

开发过程中踩过的坑、关键问题的解决方案。

| 名称 | 文件 | tags |
|------|------|------|
| sqlite-fd-leak | [sqlite-fd-leak.md](learned/sqlite-fd-leak.md) | sqlite, 连接泄漏, BaseSQLiteManager, contextmanager |
| agent-read-image-buffer | [agent-read-image-buffer.md](learned/agent-read-image-buffer.md) | claude-agent-sdk, stream-json, buffer, 图片, Read |

→ 详见 [learned/index.md](learned/index.md)

---

## Project Rules — 项目规范

开发门禁、编码规范、实现规范、技术规范、字段规范。

| 名称 | 文件 | 类别 |
|------|------|------|
| api-and-sse-conventions | [project-rules/api-and-sse-conventions.md](api-and-sse-conventions.md) | 实现规范 |
| id-and-path-safety | [project-rules/id-and-path-safety.md](id-and-path-safety.md) | 门禁 |
| model-config-conventions | [project-rules/model-config-conventions.md](model-config-conventions.md) | 实现规范 |
| workspace-authoritative-storage | [project-rules/workspace-authoritative-storage.md](workspace-authoritative-storage.md) | 实现规范 |

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
*由 harness-init 创建于 2026-09-19，索引重建于 2026-09-21*
