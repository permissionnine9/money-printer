# 架构升级说明

## 🎯 问题解决

已完成项目架构的重大升级，解决了原有的耦合问题。

## 📦 文件说明

### 新增文件

- `src/persistence/session_manager.py` - 会话状态管理器（持久化层）
- `src/agents/workflow_v2.py` - 新工作流（多轮独立架构）
- `app_v2.py` - 新UI界面
- `test_workflow_v2.py` - 测试脚本
- `MIGRATION_GUIDE.md` - 详细的迁移指南

### 旧文件（保留）

- `src/agents/workflow.py` - 旧工作流（LangGraph + interrupt）
- `app.py` - 旧UI界面

## 🚀 快速开始

### 使用新版本（推荐）

```bash
# 启动新版本应用
uv run python app_v2.py
```

访问 http://localhost:7860

### 使用旧版本

```bash
# 如果需要使用旧版本
uv run python app.py
```

## 🆚 核心区别

| 特性 | 旧版本（app.py） | 新版本（app_v2.py） |
|------|-----------------|-------------------|
| 架构 | LangGraph + interrupt | 独立步骤 + 持久化 |
| 步骤执行 | 必须连续执行 | 可独立执行 |
| 状态管理 | 单一 GraphState | 每步独立保存 |
| 灵活性 | 低 | 高 |
| 可维护性 | 低（强耦合） | 高（解耦） |

## ✨ 新版本优势

1. **解耦**：每一步独立，互不影响
2. **持久化**：每步完成后自动保存到数据库
3. **灵活**：可以从任意步骤继续执行
4. **可维护**：修改某步不影响其他步骤

## 📖 详细文档

查看 [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) 了解：
- 详细的架构对比
- 使用示例
- API 文档
- 迁移步骤

## 🎉 推荐

**强烈推荐使用新版本（V2）进行开发！**

新架构完全解决了原有的耦合问题，符合您的需求：
- ✅ 每一步之间没有耦合关系
- ✅ 每一步确认好就持久化保存
- ✅ 不再是 human-in-the-loop 的连续模式
- ✅ 可以灵活地执行和重试每个步骤
