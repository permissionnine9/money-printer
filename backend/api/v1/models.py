"""模型管理 API（生图模型 + chat 模型：key/baseUrl/modelId 关联）"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.persistence.model_manager import ModelManager, MODEL_TYPES
from backend.deps import get_model_manager

logger = logging.getLogger(__name__)

router = APIRouter()


class ModelConfigRequest(BaseModel):
    """模型配置创建/更新请求"""
    name: str = Field(..., description="模型显示名称")
    api_key: str = Field(default="", description="API Key")
    base_url: str = Field(default="", description="API Base URL（OpenAI 兼容格式，如 https://api.example.com/v1）")
    model_id: str = Field(default="", description="模型 ID（服务商提供，一般为 厂商/模型名 格式）")
    is_default: bool = Field(default=False, description="是否设为该类型的默认模型")
    model_type: str = Field(default="image", description="模型类型：'image'（生图）、'chat'（对话/LLM）、'agent'（Agent SDK 端点，Anthropic 协议）")


def _validate_model_request(request: ModelConfigRequest) -> None:
    """创建/更新共用的请求校验"""
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if request.model_type not in MODEL_TYPES:
        raise HTTPException(status_code=400, detail=f"model_type 仅支持 {list(MODEL_TYPES)}")
    if request.model_type == "image" and not request.model_id.strip():
        raise HTTPException(status_code=400, detail="生图模型的模型 ID 不能为空")


@router.get("")
async def list_models(
    model_type: str | None = None,
    model_manager: ModelManager = Depends(get_model_manager),
):
    """列出模型配置（可选按类型过滤：image / chat / agent）"""
    if model_type and model_type not in MODEL_TYPES:
        raise HTTPException(status_code=400, detail=f"model_type 仅支持 {list(MODEL_TYPES)}")

    models = model_manager.list_models(model_type=model_type)
    return {"success": True, "models": models}


@router.post("")
async def create_model(
    request: ModelConfigRequest,
    model_manager: ModelManager = Depends(get_model_manager),
):
    """新增模型配置"""
    _validate_model_request(request)

    try:
        model = model_manager.create_model(
            name=request.name.strip(),
            api_key=request.api_key.strip(),
            base_url=request.base_url.strip(),
            model_id=request.model_id.strip(),
            is_default=request.is_default,
            model_type=request.model_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"[API] 新增模型: [{request.model_type}] {request.name}")
    return {"success": True, "message": "模型配置已创建", "model": model}


@router.put("/{model_uuid}")
async def update_model(
    model_uuid: str,
    request: ModelConfigRequest,
    model_manager: ModelManager = Depends(get_model_manager),
):
    """更新模型配置"""
    _validate_model_request(request)

    try:
        model = model_manager.update_model(
            model_id=model_uuid,
            name=request.name.strip(),
            api_key=request.api_key.strip(),
            base_url=request.base_url.strip(),
            model_id_field=request.model_id.strip(),
            is_default=request.is_default,
            model_type=request.model_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not model:
        raise HTTPException(status_code=404, detail="模型配置不存在")

    return {"success": True, "message": "模型配置已更新", "model": model}


@router.post("/{model_uuid}/set-default")
async def set_default_model(
    model_uuid: str,
    model_manager: ModelManager = Depends(get_model_manager),
):
    """设置为该类型的默认模型"""
    model = model_manager.set_default(model_uuid)
    if not model:
        raise HTTPException(status_code=404, detail="模型配置不存在")

    type_label = {"image": "生图", "chat": "chat", "agent": "agent"}.get(model["model_type"], model["model_type"])
    return {"success": True, "message": f"已将「{model['name']}」设为默认{type_label}模型", "model": model}


@router.delete("/{model_uuid}")
async def delete_model(
    model_uuid: str,
    model_manager: ModelManager = Depends(get_model_manager),
):
    """删除模型配置"""
    if not model_manager.get_model(model_uuid):
        raise HTTPException(status_code=404, detail="模型配置不存在")

    success = model_manager.delete_model(model_uuid)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")

    return {"success": True, "message": "模型配置已删除"}
