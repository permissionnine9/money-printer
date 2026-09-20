"""系统设置：远程 ComfyUI 连接信息（读写 hosts.json + SSH 隧道重连）

ComfyUI GPU 容器每次重启/重建后 SSH host/port/密码都会变化，此路由提供
手动录入界面所需的后端：凭据写在 ~/.claude/skills/comfyui-restart/hosts.json
（与 comfyui-restart skill / start_comfyui_tunnel.sh 共用同一份配置），
保存后自动重启本地 SSH 隧道并探测 127.0.0.1:8188 连通性。
"""
import asyncio
import json
import logging
import subprocess
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.config import BASE_DIR

logger = logging.getLogger(__name__)

router = APIRouter()

_HOSTS_JSON = Path.home() / ".claude/skills/comfyui-restart/hosts.json"
_TUNNEL_SCRIPT = BASE_DIR.parent / "start_comfyui_tunnel.sh"
_TUNNEL_PID_FILE = Path("/tmp/comfyui_tunnel_gz15-a100.pid")
_TUNNEL_LOG = Path("/tmp/comfyui_tunnel.log")
_COMFYUI_ALIAS = "gz15-a100"
_COMFYUI_LOCAL_URL = "http://127.0.0.1:8188"
_TUNNEL_READY_TIMEOUT = 35  # 隧道脚本自带 15s 就绪等待 + 3s 重连间隔


class ComfyUIConnectionRequest(BaseModel):
    """ComfyUI SSH 连接信息（对应 hosts.json 的 gz15-a100 条目）"""
    host: str = Field(..., min_length=3, description="SSH 主机名")
    port: int = Field(..., ge=1, le=65535, description="SSH 端口")
    user: str = Field(default="root", description="SSH 用户名")
    password: str = Field(default="", description="SSH 密码（留空 = 保留原密码，仅改其他字段时用）")


def _load_hosts() -> dict:
    if not _HOSTS_JSON.exists():
        raise HTTPException(status_code=500, detail=f"未找到主机配置文件: {_HOSTS_JSON}")
    return json.loads(_HOSTS_JSON.read_text(encoding="utf-8"))


def _comfyui_alive() -> bool:
    try:
        response = httpx.get(f"{_COMFYUI_LOCAL_URL}/system_stats", timeout=3)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def _stop_tunnel() -> None:
    """停掉旧隧道（PID 文件 + 按脚本名兜底），幂等"""
    if _TUNNEL_PID_FILE.exists():
        try:
            pid = int(_TUNNEL_PID_FILE.read_text().strip())
            subprocess.run(["kill", str(pid)], capture_output=True)
        except (ValueError, OSError):
            pass
        _TUNNEL_PID_FILE.unlink(missing_ok=True)
    subprocess.run(["pkill", "-f", "start_comfyui_tunnel.sh"], capture_output=True)


def _start_tunnel() -> None:
    log_handle = _TUNNEL_LOG.open("w")
    subprocess.Popen(
        ["bash", str(_TUNNEL_SCRIPT)],
        stdout=log_handle, stderr=subprocess.STDOUT,
        start_new_session=True,  # 脱离 API 进程会话，服务重启不影响隧道
    )
    log_handle.close()


@router.get("/comfyui-connection")
async def get_comfyui_connection():
    """读取当前 ComfyUI 连接信息与隧道连通状态（密码脱敏）"""
    entry = _load_hosts()["hosts"].get(_COMFYUI_ALIAS, {})
    return {
        "host": entry.get("host", ""),
        "port": entry.get("port"),
        "user": entry.get("user", "root"),
        "password_set": bool(entry.get("password")),
        "connected": _comfyui_alive(),
    }


@router.put("/comfyui-connection")
async def update_comfyui_connection(request: ComfyUIConnectionRequest):
    """保存连接信息 → 重启 SSH 隧道 → 探测 ComfyUI 连通性"""
    hosts = _load_hosts()
    entry = hosts["hosts"].setdefault(_COMFYUI_ALIAS, {})
    entry.update({
        "host": request.host.strip(),
        "port": request.port,
        "user": request.user.strip() or "root",
    })
    if request.password:
        entry["password"] = request.password
    _HOSTS_JSON.write_text(json.dumps(hosts, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"[设置] ComfyUI 连接信息已更新: {request.host.strip()}:{request.port}")

    if not _TUNNEL_SCRIPT.exists():
        raise HTTPException(status_code=500, detail=f"未找到隧道脚本: {_TUNNEL_SCRIPT}")

    _stop_tunnel()
    await asyncio.sleep(1)
    _start_tunnel()

    deadline = asyncio.get_event_loop().time() + _TUNNEL_READY_TIMEOUT
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(2)
        if _comfyui_alive():
            logger.info("[设置] 隧道已重连，ComfyUI 可达")
            return {"connected": True, "message": "已保存并连接成功"}
    return {
        "connected": False,
        "message": "已保存，但隧道未能连通 ComfyUI（凭据错误或远程服务未启动），请检查后重试",
    }
