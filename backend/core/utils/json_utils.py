"""JSON 序列化/反序列化公共工具（SQLite JSON 列与 LLM 输出解析共用）"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def dump_json(data: Any) -> str:
    """序列化为紧凑 JSON 文本（保留中文可读性）"""
    return json.dumps(data, ensure_ascii=False)


def load_json(text: str | None, default: Any) -> Any:
    """反序列化 JSON 文本，空值/坏数据回退默认值（坏数据记录 warning 日志）"""
    try:
        return json.loads(text) if text else default
    except (ValueError, TypeError):
        logger.warning(f"JSON 列数据损坏，回退默认值: {str(text)[:120]!r}")
        return default
