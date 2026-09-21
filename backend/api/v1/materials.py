"""素材管理 API（全局素材列表 / 引用保护删除 / 孤儿文件扫描清理）"""
import logging

from fastapi import APIRouter, Depends

from backend.core.services import material_admin_service as material_admin
from backend.deps import (
    get_script_manager,
    get_script_session_manager,
    get_workspace_store,
)
from backend.schemas.material import MaterialFilesDeleteRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def list_materials(
    kind: str = "lookbook",
    store=Depends(get_workspace_store),
    sm=Depends(get_script_session_manager),
    scm=Depends(get_script_manager),
):
    """全局素材列表（kind: lookbook 核心素材 / episode 分集素材图 / upload 上传参考图 / video 视频）"""
    data = material_admin.list_materials(kind, store, sm, scm)
    return {"success": True, "data": data}


@router.delete("/image/{image_id}")
async def delete_material_image(
    image_id: str,
    store=Depends(get_workspace_store),
    sm=Depends(get_script_session_manager),
    scm=Depends(get_script_manager),
):
    """删除生成图素材（引用中返回 409；删 DB 记录 + 无共享时删磁盘文件）"""
    data = material_admin.delete_image(image_id, store, sm, scm)
    return {"success": True, "data": data}


@router.get("/orphans")
async def scan_orphan_files(
    store=Depends(get_workspace_store),
    sm=Depends(get_script_session_manager),
    scm=Depends(get_script_manager),
):
    """孤儿文件扫描（static 三目录下无 DB 记录且无引用的文件）"""
    data = material_admin.scan_orphans(store, sm, scm)
    return {"success": True, "data": data}


@router.post("/files/delete")
async def delete_material_files(
    request: MaterialFilesDeleteRequest,
    store=Depends(get_workspace_store),
    sm=Depends(get_script_session_manager),
    scm=Depends(get_script_manager),
):
    """批量删除素材文件（路径限定 static/{images,videos,uploads} 内；被引用的拒删）"""
    if not request.paths:
        return {"success": True, "data": {"deleted": [], "failed": []}}
    data = material_admin.delete_files(request.paths, store, sm, scm)
    return {"success": True, "data": data}
