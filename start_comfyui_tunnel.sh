#!/bin/bash

# 远程 ComfyUI SSH 隧道：将远程 8188 端口转发到本地 127.0.0.1:8188
# 后端通过 http://127.0.0.1:8188（经隧道）访问远程 ComfyUI API。
#
# 凭据从 ~/.claude/skills/comfyui-restart/hosts.json 的 gz15-a100 条目读取
# （与 comfyui-restart skill 共享配置，不在本脚本硬编码密码）。
#
# 特性：幂等（已通则直接退出）、断线自动重连、PID 文件管理。

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

LOCAL_PORT=8188
HOSTS_JSON="$HOME/.claude/skills/comfyui-restart/hosts.json"
HOST_ALIAS="gz15-a100"
PID_FILE="/tmp/comfyui_tunnel_${HOST_ALIAS}.pid"

cd "$(dirname "$0")"

# 从 hosts.json 读取连接信息（host/port/user/password/remote_port）
# 用 Unit Separator(\x1f) 分隔：密码可能含空格或为空，按空白分词会字段错位
IFS=$'\x1f' read -r SSH_HOST SSH_PORT SSH_USER SSH_PASS REMOTE_PORT < <(python3 - "$HOSTS_JSON" "$HOST_ALIAS" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    cfg = json.load(f)
host = cfg["hosts"][sys.argv[2]]
fields = [host["host"], str(host["port"]), host.get("user", "root"),
          host.get("password", ""), str(host.get("remote_port", 8188))]
if any("\x1f" in f for f in fields):
    sys.exit("字段值含分隔符 \\x1f，无法安全解析")
print("\x1f".join(fields))
PYEOF
)

if [ -z "$SSH_HOST" ]; then
    echo -e "${RED}无法从 $HOSTS_JSON 读取主机 $HOST_ALIAS 的连接信息${NC}"
    exit 1
fi

comfyui_reachable() {
    curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:${LOCAL_PORT}/system_stats" 2>/dev/null | grep -q "200"
}

# 幂等：隧道已通则直接退出
if comfyui_reachable; then
    echo -e "${GREEN}ComfyUI 隧道已通（127.0.0.1:${LOCAL_PORT} → ${SSH_HOST}:${REMOTE_PORT}），无需重复启动${NC}"
    exit 0
fi

# 清理残留的旧隧道进程（PID 文件存在但端口不通）
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    kill "$OLD_PID" 2>/dev/null
    rm -f "$PID_FILE"
fi

echo -e "${GREEN}启动 ComfyUI SSH 隧道：127.0.0.1:${LOCAL_PORT} → ${SSH_HOST}:${REMOTE_PORT}（断线自动重连，Ctrl+C 停止）${NC}"

start_tunnel() {
    sshpass -p "$SSH_PASS" ssh -N \
        -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
        -p "$SSH_PORT" \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -o StrictHostKeyChecking=accept-new \
        "$SSH_USER@$SSH_HOST"
}

cleanup() {
    echo ""
    echo -e "${YELLOW}停止 ComfyUI 隧道...${NC}"
    [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
    # kill $TUNNEL_PID 只能打到 sshpass，真正监听本地端口的 ssh 是其子进程，
    # 不补杀会变孤儿继续占住 8188（新隧道 bind 失败或旧转发假存活）
    pkill -f "ssh -N -L ${LOCAL_PORT}:127.0.0.1:" 2>/dev/null
    rm -f "$PID_FILE"
    echo -e "${GREEN}隧道已停止${NC}"
    exit 0
}
trap cleanup INT TERM HUP

# 断线重连循环
while true; do
    start_tunnel &
    TUNNEL_PID=$!
    echo "$TUNNEL_PID" > "$PID_FILE"

    # 等待隧道就绪（最多 15 秒）
    for i in $(seq 1 15); do
        if comfyui_reachable; then
            echo -e "${GREEN}隧道已就绪：http://127.0.0.1:${LOCAL_PORT}${NC}"
            break
        fi
        sleep 1
    done

    wait "$TUNNEL_PID"
    echo -e "${YELLOW}隧道断开，3 秒后重连...${NC}"
    sleep 3
done
