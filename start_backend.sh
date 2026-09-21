#!/bin/bash

# 设置颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}正在启动 FastAPI 后端...${NC}"

# 检查是否已安装 UV
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}未检测到 UV，正在安装...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # 检查安装是否成功
    if ! command -v uv &> /dev/null; then
        echo -e "${RED}UV 安装失败，请手动安装后重试${NC}"
        exit 1
    fi

    # 将 UV 添加到 PATH（如果使用的是默认安装路径）
    export PATH="$HOME/.cargo/bin:$PATH"
    echo -e "${GREEN}UV 安装成功${NC}"
fi

# 检查项目依赖
echo -e "${YELLOW}正在检查项目依赖...${NC}"
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}错误：未找到 pyproject.toml 文件，请确保在项目根目录运行此脚本${NC}"
    exit 1
fi

# 检查虚拟环境是否存在
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}未检测到虚拟环境，正在创建...${NC}"
    uv venv
    echo -e "${GREEN}虚拟环境创建成功！${NC}"
fi

# 激活虚拟环境
echo -e "${BLUE}正在激活虚拟环境...${NC}"
source .venv/bin/activate

# 使用 UV 同步依赖（使用清华镜像加速）
echo -e "${YELLOW}正在安装/更新项目依赖（使用清华镜像）...${NC}"
if ! uv sync --index-url https://pypi.tuna.tsinghua.edu.cn/simple; then
    echo -e "${RED}依赖安装失败，尝试使用默认源...${NC}"
    uv sync
fi

# 检查依赖安装是否成功
if [ $? -ne 0 ]; then
    echo -e "${RED}依赖安装失败，请检查网络连接和 pyproject.toml 文件${NC}"
    exit 1
fi

echo -e "${GREEN}依赖安装完成！${NC}"

# 检查环境变量文件
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}警告：未找到 .env 文件，将使用默认配置${NC}"
    echo -e "${YELLOW}如需配置 API 密钥等参数，请复制 .env.example 为 .env 并修改${NC}"
fi

# 显示虚拟环境信息
echo -e "${BLUE}虚拟环境路径：$(pwd)/.venv${NC}"
echo -e "${BLUE}Python 版本：$(python --version)${NC}"

# 启动 FastAPI 服务
echo -e "${GREEN}正在启动 FastAPI 服务...${NC}"
echo -e "${GREEN}API 文档将运行在：http://localhost:8000/docs${NC}"

# 清理残留后端：uvicorn --reload 的 graceful shutdown 可能被未完成的后台任务
# （如视频生成）卡住，上次未退干净的进程会一直占着 8000，导致本次启动直接失败。
# 按进程组整体清理（reloader 与 worker 同组，只杀 reloader 会留下占着 socket 的 worker）
if [ -n "$(lsof -ti :8000 2>/dev/null)" ]; then
    STALE_UVICORN=$(pgrep -f "uvicorn backend.main:app" | head -1)
    if [ -n "$STALE_UVICORN" ]; then
        STALE_PGID=$(ps -o pgid= -p "$STALE_UVICORN" | tr -d ' ')
        echo -e "${YELLOW}端口 8000 被残留后端占用（PID $STALE_UVICORN），正在按进程组清理...${NC}"
        kill -9 -- -"$STALE_PGID" 2>/dev/null
        sleep 1
    fi
fi
if [ -n "$(lsof -ti :8000 2>/dev/null)" ]; then
    echo -e "${RED}错误：端口 8000 被其他进程占用（PID: $(lsof -ti :8000 | tr '\n' ' ')），请手动处理${NC}"
    exit 1
fi

# 使用虚拟环境中的 uvicorn（graceful shutdown 限时 10 秒，防止退出被后台任务卡住）
.venv/bin/uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10
