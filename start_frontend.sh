#!/bin/bash

# 设置颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}正在启动 React 前端...${NC}"

# 检查 frontend 目录是否存在
if [ ! -d "frontend" ]; then
    echo -e "${RED}错误：未找到 frontend 目录${NC}"
    exit 1
fi

cd frontend

# 检查是否已安装 Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}错误：未检测到 Node.js，请先安装 Node.js${NC}"
    echo -e "${YELLOW}建议：使用 nvm 安装 Node.js：https://github.com/nvm-sh/nvm${NC}"
    exit 1
fi

# 检查 package.json 是否存在
if [ ! -f "package.json" ]; then
    echo -e "${RED}错误：未找到 package.json 文件${NC}"
    exit 1
fi

# 检查 node_modules 是否存在
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}未检测到 node_modules，正在安装依赖...${NC}"

    # 使用淘宝镜像源安装依赖
    echo -e "${BLUE}正在使用淘宝镜像安装依赖...${NC}"
    npm install --registry=https://registry.npmmirror.com

    if [ $? -ne 0 ]; then
        echo -e "${RED}依赖安装失败，尝试使用默认源...${NC}"
        npm install
    fi

    if [ $? -ne 0 ]; then
        echo -e "${RED}依赖安装失败，请检查网络连接和 package.json 文件${NC}"
        exit 1
    fi

    echo -e "${GREEN}依赖安装完成！${NC}"
fi

# 显示环境信息
echo -e "${BLUE}Node.js 版本：$(node --version)${NC}"
echo -e "${BLUE}npm 版本：$(npm --version)${NC}"

# 启动前端开发服务器
echo -e "${GREEN}正在启动前端开发服务器...${NC}"
echo -e "${GREEN}应用将运行在：http://localhost:5173${NC}"

npm run dev
