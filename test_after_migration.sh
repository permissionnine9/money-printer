#!/bin/bash
# 迁移后快速测试脚本

echo "=========================================="
echo "  迁移后功能测试"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试 Python 导入
echo "1️⃣  测试 Python 模块导入..."
python3 verify_migration.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Python 模块导入测试通过${NC}"
else
    echo -e "${RED}❌ Python 模块导入测试失败${NC}"
    exit 1
fi
echo ""

# 提示测试后端
echo "=========================================="
echo "2️⃣  后端测试"
echo "=========================================="
echo ""
echo "请在新终端中运行以下命令启动后端："
echo -e "${YELLOW}cd backend && uv run uvicorn backend.main:app --reload${NC}"
echo ""
echo "然后访问: http://localhost:8000/docs"
echo "确认 API 文档可以正常显示"
echo ""
read -p "后端测试是否通过？(y/n): " backend_ok

if [ "$backend_ok" != "y" ]; then
    echo -e "${RED}❌ 后端测试未通过，请检查错误信息${NC}"
    exit 1
fi
echo -e "${GREEN}✅ 后端测试通过${NC}"
echo ""

# 提示测试前端
echo "=========================================="
echo "3️⃣  前端测试"
echo "=========================================="
echo ""
echo "请在新终端中运行以下命令启动前端："
echo -e "${YELLOW}cd frontend && npm run dev${NC}"
echo ""
echo "然后访问: http://localhost:5173"
echo "确认前端界面可以正常显示"
echo ""
read -p "前端测试是否通过？(y/n): " frontend_ok

if [ "$frontend_ok" != "y" ]; then
    echo -e "${RED}❌ 前端测试未通过，请检查错误信息${NC}"
    exit 1
fi
echo -e "${GREEN}✅ 前端测试通过${NC}"
echo ""

# 可选：测试 Gradio
echo "=========================================="
echo "4️⃣  Gradio 测试（可选）"
echo "=========================================="
echo ""
read -p "是否测试 Gradio 版本？(y/n): " test_gradio

if [ "$test_gradio" = "y" ]; then
    echo "请在新终端中运行："
    echo -e "${YELLOW}uv run python app_v2_improved.py${NC}"
    echo ""
    echo "然后访问: http://localhost:7860"
    echo ""
    read -p "Gradio 测试是否通过？(y/n): " gradio_ok

    if [ "$gradio_ok" != "y" ]; then
        echo -e "${RED}❌ Gradio 测试未通过${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ Gradio 测试通过${NC}"
fi
echo ""

# 测试完成
echo "=========================================="
echo "  🎉 所有测试通过！"
echo "=========================================="
echo ""
echo "迁移成功完成！现在可以："
echo ""
echo "1. 删除备份目录:"
echo "   ${YELLOW}rm -rf src.backup${NC}"
echo ""
echo "2. 提交更改到 Git:"
echo "   ${YELLOW}git add .${NC}"
echo "   ${YELLOW}git commit -m 'refactor: 重命名 src 为 core，明确核心业务逻辑层'${NC}"
echo ""
echo "3. 继续开发！"
echo ""
