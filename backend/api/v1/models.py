"""模型管理 API（生图模型 + chat 模型：key/baseUrl/modelId 关联）"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.core.persistence.model_manager import ModelManager, MODEL_TYPES
from backend.deps import get_model_manager
from backend.schemas.model import ModelConfigRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def _validate_model_type(model_type: str) -> None:
    """模型类型白名单校验（列表过滤与创建/更新共用）"""
    if model_type not in MODEL_TYPES:
        raise HTTPException(status_code=400, detail=f"model_type 仅支持 {list(MODEL_TYPES)}")


def _validate_model_request(request: ModelConfigRequest) -> None:
    """创建/更新共用的请求校验"""
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    _validate_model_type(request.model_type)
    if request.model_type == "image" and not request.model_id.strip():
        raise HTTPException(status_code=400, detail="生图模型的模型 ID 不能为空")


@router.get("")
async def list_models(
    model_type: str | None = None,
    model_manager: ModelManager = Depends(get_model_manager),
):
    """列出模型配置（可选按类型过滤：image / chat / agent）"""
    if model_type:
        _validate_model_type(model_type)

    models = model_manager.list_models(model_type=model_type)
    return {"success": True, "data": {"models": models}}


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
    return {"success": True, "data": {"model": model}}


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

    return {"success": True, "data": {"model": model}}


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
    return {
        "success": True,
        "message": f"已将「{model['name']}」设为默认{type_label}模型",
        "data": {"model": model},
    }


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

    return {"success": True, "data": {"deleted": True}}
