# AI视频创作智能体

基于多轮独立架构的智能视频创作工作流，支持从脚本到视频的全流程自动化。

## 🎉 架构升级（V2）

**新版本采用多轮独立架构，完全解决了原有的耦合问题！**

### V2 核心优势

- ✅ **完全解耦**：每个步骤独立执行，互不耦合
- ✅ **自动持久化**：每步完成后立即保存到数据库
- ✅ **灵活控制**：可以从任意步骤继续执行
- ✅ **易于维护**：修改某步不影响其他步骤

### 快速开始

```bash
# 使用新版本（推荐）
uv run python app_v2.py

# 使用旧版本
uv run python app.py
```

📖 详细说明请查看：
- [UPGRADE.md](./UPGRADE.md) - 升级说明
- [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) - 迁移指南
- [ARCHITECTURE.md](./ARCHITECTURE.md) - 架构对比

## 功能特性

- **脚本优化**：使用 Gemini 2.0 Flash 自动优化视频脚本，丰富细节，设计分片
- **素材图片生成**：使用 Nano Banana Pro 生成包含所有视觉要素的素材图
- **分镜头帧生成**：为每个分片生成首尾帧图片
- **视频生成**：支持多种视频模型（即梦、wan2.2、豆包-seedance）基于首尾帧生成视频片段
- **人机交互**：每个步骤都支持人工审核确认

## 技术栈

- **Agent框架**: LangGraph
- **LLM**: Google Gemini 2.0 Flash (`gemini-2.5-flash`)
- **图片生成**: Nano Banana Pro (`gemini-3-pro-image-preview`)
- **视频生成**: 支持多种模型（即梦、wan2.2、豆包-seedance）
- **前端界面**: Gradio
- **包管理**: UV

## 安装

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装依赖（使用清华镜像加速）
uv sync

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填写 VERTEX_API_KEY
```

## 使用

```bash
# 启动应用
uv run python app.py
```

然后在浏览器中访问 http://localhost:7860

## 工作流程

1. **输入脚本和参数** - 用户输入视频脚本，选择分辨率、宽高比、语言、美学风格、视角等参数
2. **脚本优化** - LLM 优化脚本内容，自动分片（每片不超过8秒）
3. **素材图片生成** - 使用 Nano Banana Pro 生成1-2张包含所有视觉要素的素材图
4. **分镜头帧生成** - 为每个分片生成首帧和尾帧图片（基于素材图风格）
5. **视频生成** - 使用 Veo 3.1 基于首尾帧和分片脚本生成视频片段

每个步骤都需要用户确认后才会继续。

## 项目结构

```
money-print/
├── app.py                 # Gradio 前端界面
├── pyproject.toml         # 项目配置和依赖
├── src/
│   ├── config.py          # 配置管理
│   ├── models/            # 数据模型
│   │   └── video_models.py
│   ├── services/          # 服务模块
│   │   ├── llm_service.py     # LLM 服务（脚本优化）
│   │   ├── image_service.py   # 图片生成服务（Nano Banana Pro）
│   │   └── video_service.py   # 视频生成服务（Veo 3.1）
│   └── agents/            # Agent 模块
│       └── workflow.py    # LangGraph 工作流
└── static/                # 静态文件存储
    ├── images/            # 生成的图片
    └── videos/            # 生成的视频
```

## API配置

项目使用 Google Gemini API，需要配置 API 密钥：

1. 在项目根目录创建 `.env` 文件
2. 添加 `VERTEX_API_KEY=your_api_key`

API密钥格式：`AIza...` 开头的39字符字符串

## 模型说明

### Nano Banana Pro (图片生成)
- 模型ID：`gemini-3-pro-image-preview`
- 支持宽高比：1:1, 2:3, 3:2, 3:4, 4:3, 9:16, 16:9等
- 支持分辨率：1K, 2K, 4K
- 高质量图片生成

### Veo 3.1 (视频生成)
- 模型ID：`veo-3.1-generate-preview`
- 支持宽高比：16:9, 9:16
- 支持时长：5-8秒
- 支持图片到视频转换

## 测试

### 测试架构核心功能（不依赖API）

```bash
# 测试持久化、状态管理等核心功能
uv run python test_architecture.py
```

### 测试完整工作流（需要API）

```bash
# 测试包含API调用的完整流程
uv run python test_workflow_v2.py
```

## 注意事项

- 视频生成可能需要较长时间（每个片段约1-2分钟），请耐心等待
- 生成的图片和视频保存在 `static/` 目录下
- 建议在稳定的网络环境下使用
- API调用可能产生费用，请注意配额管理

## 许可证

MIT
