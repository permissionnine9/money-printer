"""Agent 模型端点环境注入

从模型管理读取 model_type='agent' 的默认模型（Anthropic 协议 base_url/api_key/model_id），
构造子进程环境变量。Agent SDK 依赖本机 Claude Code CLI，CLI 通过以下变量寻址端点：
- ANTHROPIC_BASE_URL:   Anthropic 协议兼容网关地址
- ANTHROPIC_AUTH_TOKEN: Bearer 认证（兼容网关常用）
- ANTHROPIC_MODEL:      模型 ID
"""
import os


class AgentModelNotConfiguredError(Exception):
    """未配置默认 agent 模型端点"""


def build_agent_env() -> dict[str, str]:
    """构造 agent 子进程环境（继承当前进程环境并注入端点变量）

    Returns:
        完整环境变量 dict

    Raises:
        AgentModelNotConfiguredError: 模型管理中没有 model_type='agent' 的默认模型
    """
    # 延迟导入避免持久层初始化顺序耦合
    from backend.core.persistence.model_manager import ModelManager

    model = ModelManager().get_default_model("agent")
    if not model:
        raise AgentModelNotConfiguredError(
            "未配置 agent 模型端点：请在「模型管理」新增 model_type=agent 的模型"
            "（Anthropic 协议 base_url/api_key/model_id）并设为默认"
        )

    env = dict(os.environ)
    # 清掉本机可能存在的同名变量，避免优先级混乱
    for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        env.pop(key, None)

    base_url = (model.get("base_url") or "").strip().rstrip("/")
    api_key = (model.get("api_key") or "").strip()
    model_id = (model.get("model_id") or "").strip()

    if not model_id:
        raise AgentModelNotConfiguredError("agent 模型配置缺少 model_id")

    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    if api_key:
        # AUTH_TOKEN(Bearer) 与 API_KEY(x-api-key) 同时注入，兼容官方 API 与各类网关
        env["ANTHROPIC_AUTH_TOKEN"] = api_key
        env["ANTHROPIC_API_KEY"] = api_key
    env["ANTHROPIC_MODEL"] = model_id
    env["CLAUDE_AGENT_SDK_CLIENT_APP"] = "money-printer/2.0"
    return env
