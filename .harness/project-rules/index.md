# Project Rules 项目规范索引

> 最后更新: 2026-09-19

| 名称 | 文件 | 类别 | tags |
|------|------|------|------|
| api-and-sse-conventions | [api-and-sse-conventions.md](api-and-sse-conventions.md) | 实现规范 | API, SSE, 响应包络, 异常处理, agent-runs, fetchSSE |
| id-and-path-safety | [id-and-path-safety.md](id-and-path-safety.md) | 门禁 | 安全, 门禁, ID校验, 路径穿越, workspace-store |
| model-config-conventions | [model-config-conventions.md](model-config-conventions.md) | 实现规范 | 模型配置, ModelManager, image_models, build_agent_env, claude-agent-sdk, Agent调用, MCP, 生图服务, ImageService |
| workspace-authoritative-storage | [workspace-authoritative-storage.md](workspace-authoritative-storage.md) | 实现规范 | 架构, 存储, workspace, 文件化, 迁移, workspace-store |

**类别说明:**
- **门禁** — 禁止做的事情，触犯即阻塞
- **编码规范** — 代码风格、命名、注释等
- **实现规范** — 设计模式、架构约束、性能策略（如不能默认用 limit 限制查询）
- **技术规范** — 技术选型、版本要求、中间件使用
- **字段规范** — 数据库字段、API 字段、枚举定义
