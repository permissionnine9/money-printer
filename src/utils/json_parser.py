"""JSON解析工具 - 统一处理LLM响应的JSON解析"""
import json
import re
from typing import Any


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
    raise ValueError(f"无法解析JSON响应: {text[:200]}...")
