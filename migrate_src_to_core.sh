#!/bin/bash
# /src 到 /core 的迁移脚本
# 用法: bash migrate_src_to_core.sh

set -e  # 遇到错误立即退出

echo "=========================================="
echo "  /src → /core 迁移脚本"
echo "=========================================="
echo ""

# 检查是否存在 src 目录
if [ ! -d "src" ]; then
    echo "❌ 错误：src 目录不存在"
    exit 1
fi

# 检查是否已存在 core 目录
if [ -d "core" ]; then
    echo "❌ 错误：core 目录已存在，请先删除或备份"
    exit 1
fi

echo "步骤 1/4: 备份 src 目录..."
cp -r src src.backup
echo "✓ 已创建备份: src.backup"
echo ""

echo "步骤 2/4: 重命名 src → core..."
mv src core
echo "✓ 目录已重命名"
echo ""

echo "步骤 3/4: 更新导入语句..."
echo "  - 更新 backend/*.py"
find backend -name "*.py" -type f -exec sed -i '' 's/from src\./from core./g' {} \;
find backend -name "*.py" -type f -exec sed -i '' 's/import src\./import core./g' {} \;

echo "  - 更新 core/*.py"
find core -name "*.py" -type f -exec sed -i '' 's/from src\./from core./g' {} \;
find core -name "*.py" -type f -exec sed -i '' 's/import src\./import core./g' {} \;

echo "  - 更新根目录 *.py"
find . -maxdepth 1 -name "*.py" -type f -exec sed -i '' 's/from src\./from core./g' {} \;
find . -maxdepth 1 -name "*.py" -type f -exec sed -i '' 's/import src\./import core./g' {} \;

echo "✓ 导入语句已更新"
echo ""

echo "步骤 4/4: 验证迁移结果..."
echo "  检查是否还有 'from src.' 导入..."
REMAINING=$(grep -r "from src\." backend core *.py 2>/dev/null | grep -v ".pyc" | wc -l)
if [ "$REMAINING" -eq 0 ]; then
    echo "✓ 所有导入语句已更新"
else
    echo "⚠️  警告：仍有 $REMAINING 处未更新的导入语句"
    grep -r "from src\." backend core *.py 2>/dev/null | grep -v ".pyc"
fi
echo ""

echo "=========================================="
echo "  迁移完成！"
echo "=========================================="
echo ""
echo "后续步骤："
echo "1. 运行测试确保功能正常"
echo "2. 更新 CLAUDE.md 和 README.md 中的说明"
echo "3. 如果一切正常，删除备份: rm -rf src.backup"
echo ""
echo "如果需要回滚："
echo "  rm -rf core && mv src.backup src"
echo ""
