#!/bin/bash

# 一键启动前后端（并行执行 start_backend.sh 和 start_frontend.sh）
# 用法：./start_all.sh，按 Ctrl+C 同时停止所有服务

# 设置颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 切换到脚本所在目录，保证子脚本在项目根目录运行
cd "$(dirname "$0")"

# 开启 job control，让每个后台脚本运行在独立进程组，便于整组清理（含 uvicorn reload 子进程）
set -m

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    echo -e "${YELLOW}正在停止所有服务...${NC}"
    [ -n "$BACKEND_PID" ] && kill -- -"$BACKEND_PID" 2>/dev/null
    [ -n "$FRONTEND_PID" ] && kill -- -"$FRONTEND_PID" 2>/dev/null
    wait 2>/dev/null
    echo -e "${GREEN}所有服务已停止${NC}"
    exit 0
}

trap cleanup INT TERM

echo -e "${GREEN}正在同时启动后端（http://localhost:8000/docs）和前端（http://localhost:5173）...${NC}"
echo -e "${GREEN}按 Ctrl+C 停止所有服务${NC}"

bash start_backend.sh &
BACKEND_PID=$!

bash start_frontend.sh &
FRONTEND_PID=$!

wait
