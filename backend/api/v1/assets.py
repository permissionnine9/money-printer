"""会话资产管理 API（素材管理台：音频管理 / 素材管理）"""
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.deps import get_session_manager
from backend.core.persistence.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter()

# 上传文件保存目录
ASSET_UPLOAD_DIR = Path("static/uploads")
AUDIO_DIR = ASSET_UPLOAD_DIR / "audio"

# 允许的文件类型
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/aac", "audio/flac", "audio/ogg", "audio/x-m4a", "audio/m4a"}
# 扩展名回退（部分客户端上传时 MIME 为 application/octet-stream）
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


@router.get("/{session_id}")
async def list_assets(
    session_id: str,
    asset_type: str | None = None,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """列出会话资产（可选按类型过滤：audio / image）"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    if asset_type and asset_type not in ("audio", "image"):
        raise HTTPException(status_code=400, detail="asset_type 仅支持 audio 或 image")

    assets = session_manager.list_assets(session_id, asset_type=asset_type)
    return {"success": True, "assets": assets}


@router.post("/{session_id}/upload")
async def upload_asset(
    session_id: str,
    asset_type: str,
    file: UploadFile = File(...),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """上传资产文件（音频或图片），登记到会话素材库

    Args:
        asset_type: 'audio' 或 'image'
    """
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    if asset_type not in ("audio", "image"):
        raise HTTPException(status_code=400, detail="asset_type 仅支持 audio 或 image")

    content_type = file.content_type or ""
    file_ext = Path(file.filename or "").suffix.lower()
    if asset_type == "audio" and content_type not in AUDIO_TYPES and file_ext not in AUDIO_EXTS:
        raise HTTPException(status_code=400, detail=f"只能上传音频文件（收到 {content_type or '未知类型'}）")
    if asset_type == "image" and content_type not in IMAGE_TYPES and file_ext not in IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"只能上传图片文件（收到 {content_type or '未知类型'}）")

    # 保存文件
    target_dir = AUDIO_DIR if asset_type == "audio" else ASSET_UPLOAD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    file_ext = Path(file.filename or "asset.bin").suffix or (".mp3" if asset_type == "audio" else ".png")
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = target_dir / unique_filename

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")
    finally:
        file.file.close()

    relative_path = f"{file_path}"
    size_kb = round(file_path.stat().st_size / 1024, 1)

    # 登记到会话素材库
    asset = session_manager.add_asset(
        session_id,
        asset_type=asset_type,
        name=file.filename or unique_filename,
        file_path=relative_path,
        meta={"size_kb": size_kb},
    )
    logger.info(f"[API] 资产上传成功: {asset_type} {file.filename} -> {relative_path}")

    return {"success": True, "message": "文件上传成功", "asset": asset}


@router.delete("/{session_id}/{asset_id}")
async def delete_asset(
    session_id: str,
    asset_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """删除会话资产记录（磁盘文件保留）"""
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    asset = session_manager.get_asset(asset_id)
    if not asset or asset["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="资产不存在")

    success = session_manager.delete_asset(session_id, asset_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除资产失败")

    return {"success": True, "message": "资产已删除"}
