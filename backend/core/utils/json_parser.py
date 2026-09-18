"""JSON/markdown 提取工具 - 统一处理 LLM 响应的解析"""
import json
import re
from typing import Any, Optional


def parse_json_response(response_text: str, default: Any = None) -> dict:
    """统一的JSON响应解析函数

    Args:
        response_text: LLM返回的原始文本
        default: 解析失败时的默认值

    Returns:
        解析后的字典，解析失败返回default或抛出异常

    Raises:
        ValueError: 当无法解析且没有提供default时
    """
    if not response_text:
        if default is not None:
            return default
        raise ValueError("响应文本为空")

    text = response_text.strip()

    # 清理markdown代码块标记
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试正则提取JSON对象
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # 解析失败
    if default is not None:
        return default
    # 增强错误信息，显示更多上下文
    error_msg = f"无法解析JSON响应。原始文本长度: {len(text)}"
    if len(text) > 200:
        error_msg += f"，前200字符: {text[:200]}"
    else:
        error_msg += f"，完整文本: {text}"
    raise ValueError(error_msg)


def extract_markdown(text: str) -> str:
    """从 LLM 输出提取 markdown（剥掉 ```fence）"""
    text = text.strip()
    fence = re.search(r"```(?:markdown|md)?\s*\n(.*?)```", text, re.DOTALL)
    return fence.group(1).strip() if fence else text


def extract_json_array(text: str) -> Optional[list]:
    """从 LLM 输出提取 JSON 数组（dict 值兜底 + fence 正则兜底）"""
    parsed = parse_json_response(text, default=None)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for value in parsed.values():
            if isinstance(value, list):
                return value
    fence = re.search(r"\[\s*\{.*\}\s*\]", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(0))
        except json.JSONDecodeError:
            return None
    return None


def is_valid_mindmap(markdown: str) -> bool:
    """markdown 导图有效性：非空且以 # 层级标题开头"""
    return bool(markdown and markdown.lstrip().startswith("#"))
