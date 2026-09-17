"""提示词管理 API（分片镜头 skill 提示词，markdown 文件形式保存）"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.services.prompt_manager import get_prompt_manager, PromptManager

logger = logging.getLogger(__name__)

router = APIRouter()


class PromptUpdateRequest(BaseModel):
    """提示词保存请求"""
    content: str = Field(..., description="提示词模板内容（markdown）")


def _get_manager() -> PromptManager:
    return get_prompt_manager()


@router.get("")
async def list_prompts():
    """列出全部提示词模板"""
    manager = _get_manager()
    prompts = manager.list_prompts()
    return {"success": True, "prompts": prompts}


@router.get("/{name}")
async def get_prompt(name: str):
    """获取单个提示词模板内容"""
    manager = _get_manager()
    try:
        content = manager.load_prompt(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if content is None:
        raise HTTPException(status_code=404, detail=f"提示词模板不存在: {name}")

    return {
        "success": True,
        "prompt": {
            "name": name,
            "description": manager.extract_description(content),
            "content": content,
        },
    }


@router.put("/{name}")
async def update_prompt(name: str, request: PromptUpdateRequest):
    """保存提示词模板（markdown 文件覆盖写，无版本管理）"""
    manager = _get_manager()
    try:
        existing = manager.load_prompt(name)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"提示词模板不存在: {name}")
        manager.save_prompt(name, request.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "success": True,
        "message": "提示词已保存",
        "prompt": {
            "name": name,
            "description": manager.extract_description(request.content),
        },
    }
