# /src 目录迁移指南

## 📊 现状分析

### /src 目录的使用情况

**✅ 所有文件都在使用中**，没有可以删除的文件：

```
src/
├── agents/
│   └── workflow_v2.py         ← backend 使用（工作流编排）
├── config.py                   ← backend 使用（全局配置）
├── models/
│   └── video_models.py        ← backend 使用（数据模型）
├── persistence/
│   └── session_manager.py     ← backend 使用（会话管理）
├── services/
│   ├── llm_service.py         ← workflow_v2 使用
│   ├── image_service.py       ← workflow_v2 使用
│   ├── video_service.py       ← workflow_v2 使用
│   ├── video_service_wan22.py ← workflow_v2 使用
│   └── oss_service.py         ← video_service_wan22 使用
└── utils/
    └── json_parser.py         ← llm_service 使用
```

### 依赖关系

```
┌──────────────────────────────────────────────────┐
│         Backend API (FastAPI)                    │
│    /backend/api/v1/*.py                         │
└──────────────┬───────────────────────────────────┘
               │
               ├─► SessionManager (src/persistence/)
               │
               └─► VideoCreationWorkflowV2 (src/agents/)
                        │
                        ├─► LLMService (src/services/)
                        ├─► ImageService (src/services/)
                        ├─► VideoService (src/services/)
                        ├─► OSSService (src/services/)
                        └─► Models (src/models/)

┌──────────────────────────────────────────────────┐
│       app_v2_improved.py (Gradio)                │
└──────────────┬───────────────────────────────────┘
               │
               └─► VideoCreationWorkflowV2 (src/agents/)
                        └─► (同上)
```

## 🎯 迁移方案对比

### 方案一：保留 /src，重命名为 /core（推荐 ⭐）

**优点：**
- ✅ 清晰的分层架构：core（业务逻辑）+ backend（API）+ frontend（UI）
- ✅ 支持多种部署方式（API + Gradio）
- ✅ 符合"关注点分离"原则
- ✅ 代码结构清晰，易于维护

**操作步骤：**

```bash
# 1. 执行迁移脚本
chmod +x migrate_src_to_core.sh
bash migrate_src_to_core.sh

# 2. 测试后端
cd backend
uv run uvicorn backend.main:app --reload

# 3. 测试前端
cd frontend
npm run dev

# 4. 如果测试通过，删除备份
rm -rf src.backup

# 5. 更新文档
# - CLAUDE.md: 将所有 /src 改为 /core
# - README.md: 说明新的目录结构
```

**新的目录结构：**
```
money-print/
├── core/                    ← 核心业务逻辑（原 src）
│   ├── agents/
│   ├── models/
│   ├── persistence/
│   ├── services/
│   └── utils/
├── backend/                 ← FastAPI 后端 API
│   ├── api/
│   ├── schemas/
│   └── main.py
├── frontend/                ← React 前端
│   ├── src/
│   └── package.json
└── data/                    ← 数据存储（SQLite等）
```

---

### 方案二：只使用 React + FastAPI，移除 Gradio

如果确定不需要 Gradio 版本：

**操作步骤：**

```bash
# 1. 删除 Gradio 相关文件
rm app_v2_improved.py
rm test_workflow_complete.py

# 2. 可选：重命名 /src 为 /core
bash migrate_src_to_core.sh

# 3. 更新 README.md
# - 说明项目只支持 React + FastAPI 架构
# - 移除 Gradio 相关说明
```

---

### 方案三：将 /src 迁移到 /backend/core（不推荐 ❌）

**缺点：**
- ❌ Gradio 版本将无法使用
- ❌ backend 目录会变得臃肿
- ❌ 失去了业务逻辑的独立性
- ❌ 如果未来需要其他应用使用业务逻辑，会造成代码重复

**不推荐这个方案**，除非：
- 完全放弃 Gradio 版本
- 确定不会有其他应用需要使用这些业务逻辑

---

## 📝 决策清单

### 需要回答的问题

1. **是否还需要 Gradio 版本？**
   - ✅ 需要 → 选择方案一（重命名为 /core）
   - ❌ 不需要 → 选择方案二（删除 Gradio，可选择重命名）

2. **是否希望业务逻辑独立于框架？**
   - ✅ 是 → 选择方案一（保留独立的 core）
   - ❌ 否 → 可以考虑方案三（但不推荐）

3. **未来是否可能有其他应用使用这些业务逻辑？**
   - ✅ 可能 → 必须选择方案一（保留独立的 core）
   - ❌ 不会 → 方案二或方案三

### 推荐选择

基于以上分析，**强烈推荐方案一**：

```bash
✅ 重命名 /src → /core
✅ 保留 app_v2_improved.py（Gradio 版本，可选）
✅ 保持清晰的分层架构
```

## 🚀 执行迁移（方案一）

### 第一步：执行迁移脚本

```bash
# 确保在项目根目录
cd /Users/hecf23/work/money-print

# 执行迁移
chmod +x migrate_src_to_core.sh
bash migrate_src_to_core.sh
```

### 第二步：测试功能

```bash
# 测试后端
cd backend
uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 测试前端（新终端）
cd frontend
npm run dev

# 测试 Gradio（可选，新终端）
uv run python app_v2_improved.py
```

### 第三步：更新文档

需要更新的文件：
- [ ] CLAUDE.md：将 `/src` 改为 `/core`
- [ ] README.md：更新目录结构说明
- [ ] pyproject.toml：确认包名（如果需要）

### 第四步：清理

```bash
# 如果一切正常，删除备份
rm -rf src.backup

# 提交更改
git add .
git commit -m "refactor: 重命名 src 为 core，明确核心业务逻辑层"
```

## 🔄 回滚方案

如果迁移出现问题：

```bash
# 删除 core 目录
rm -rf core

# 恢复 src
mv src.backup src

# 恢复导入语句（如果已修改）
# 需要手动修改或使用版本控制回滚
git checkout -- backend/ app_v2_improved.py test_workflow_complete.py
```

## 📚 迁移后的项目结构

```
money-print/
├── core/                        # 核心业务逻辑层（原 src）
│   ├── agents/                  # 工作流编排
│   │   └── workflow_v2.py
│   ├── config.py                # 全局配置
│   ├── models/                  # 数据模型
│   │   └── video_models.py
│   ├── persistence/             # 持久化层
│   │   └── session_manager.py
│   ├── services/                # 服务层
│   │   ├── llm_service.py
│   │   ├── image_service.py
│   │   ├── video_service.py
│   │   ├── video_service_wan22.py
│   │   └── oss_service.py
│   └── utils/                   # 工具类
│       └── json_parser.py
│
├── backend/                     # FastAPI 后端 API 层
│   ├── main.py
│   ├── deps.py
│   ├── api/v1/                  # RESTful API
│   └── schemas/                 # API 数据模型
│
├── frontend/                    # React 前端 UI 层
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   └── stores/
│   └── package.json
│
├── data/                        # 数据存储
│   └── sessions.db
│
├── static/                      # 静态资源
│   ├── images/
│   └── videos/
│
├── app_v2_improved.py           # Gradio 独立应用（可选）
├── pyproject.toml               # 项目配置
└── README.md                    # 项目文档
```

## 🎓 架构说明（迁移后）

### 分层架构

1. **Core 层（业务逻辑）**
   - 位置：`/core`
   - 职责：核心业务逻辑、数据模型、服务实现
   - 特点：框架无关、可复用

2. **Backend 层（API）**
   - 位置：`/backend`
   - 职责：RESTful API、路由、请求/响应处理
   - 依赖：Core 层

3. **Frontend 层（UI）**
   - 位置：`/frontend`
   - 职责：用户界面、交互逻辑
   - 依赖：Backend API

### 部署方式

支持两种部署方式：

1. **前后端分离（推荐）**
   ```bash
   # 后端
   cd backend && uvicorn backend.main:app

   # 前端
   cd frontend && npm run build && npm run preview
   ```

2. **Gradio 独立应用**
   ```bash
   uv run python app_v2_improved.py
   ```

---

## ❓ 常见问题

### Q1: 为什么不直接删除 /src？

A: `/src` 中所有文件都在使用，删除会导致应用无法运行。

### Q2: 为什么推荐重命名为 /core 而不是迁移到 /backend？

A:
- Core 层是业务逻辑，应该独立于框架
- 支持多种部署方式（API + Gradio）
- 更好的代码组织和可维护性

### Q3: 迁移会影响现有功能吗？

A: 不会。迁移脚本只是重命名目录和更新导入语句，不修改业务逻辑。

### Q4: 如果不需要 Gradio，可以删除 app_v2_improved.py 吗？

A: 可以。如果只使用 React + FastAPI 架构，可以删除 Gradio 相关文件。

### Q5: 迁移后需要重新安装依赖吗？

A: 不需要。Python 包名没有变化，只是目录结构调整。

---

## 📞 需要帮助？

如果在迁移过程中遇到问题：

1. 检查迁移日志输出
2. 运行测试确认功能
3. 使用回滚方案恢复
4. 查看 git diff 确认更改

---

**建议：立即执行方案一的迁移，保持清晰的架构！** 🚀
