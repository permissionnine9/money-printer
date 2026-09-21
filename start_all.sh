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
TUNNEL_PID=""

cleanup() {
    echo ""
    echo -e "${YELLOW}正在停止所有服务...${NC}"
    [ -n "$BACKEND_PID" ] && kill -- -"$BACKEND_PID" 2>/dev/null
    [ -n "$FRONTEND_PID" ] && kill -- -"$FRONTEND_PID" 2>/dev/null
    [ -n "$TUNNEL_PID" ] && kill -- -"$TUNNEL_PID" 2>/dev/null

    # uvicorn 的 graceful shutdown 可能被未完成的后台任务（如视频生成）卡住，
    # 限时等待后对仍存活的进程组 SIGKILL 补刀，否则脚本会挂在下面的 wait 上
    for _ in 1 2 3; do
        if ! kill -0 -- -"$BACKEND_PID" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    [ -n "$BACKEND_PID" ] && kill -9 -- -"$BACKEND_PID" 2>/dev/null
    [ -n "$FRONTEND_PID" ] && kill -9 -- -"$FRONTEND_PID" 2>/dev/null
    [ -n "$TUNNEL_PID" ] && kill -9 -- -"$TUNNEL_PID" 2>/dev/null

    # 兜底：后端设置接口（settings.py）以 start_new_session 拉起的隧道
    # 不在上述任何进程组内，需要单独清理
    pkill -f "start_comfyui_tunnel.sh" 2>/dev/null

    wait 2>/dev/null
    echo -e "${GREEN}所有服务已停止${NC}"
    exit 0
}

# HUP：直接关闭终端窗口时脚本收到 SIGHUP，若不捕获则 cleanup 不执行，
# 后台服务组会全部变孤儿（继续占用端口，下次启动失败）
trap cleanup INT TERM HUP

echo -e "${GREEN}正在同时启动后端（http://localhost:8000/docs）和前端（http://localhost:5173）...${NC}"
echo -e "${GREEN}按 Ctrl+C 停止所有服务${NC}"

# ComfyUI SSH 隧道（后台保活，将远程 8188 转发到本地）
bash start_comfyui_tunnel.sh &
TUNNEL_PID=$!

bash start_backend.sh &
BACKEND_PID=$!

bash start_frontend.sh &
FRONTEND_PID=$!

wait
