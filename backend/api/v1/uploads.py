"""
文件上传 API
"""
from fastapi import APIRouter, File, UploadFile, HTTPException

from backend.api.v1._upload import UPLOAD_ROOT, save_upload

router = APIRouter()

# 扩展名白名单（content_type 可被客户端伪造，落盘前以扩展名为准）
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
    """上传图片文件"""
    # 验证文件类型
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只能上传图片文件")

    file_path = save_upload(file, UPLOAD_ROOT, default_ext=".png", allowed_exts=IMAGE_EXTS)

    # 返回文件路径（相对路径）
    relative_path = f"static/uploads/{file_path.name}"

    return {
        "success": True,
        "message": "文件上传成功",
        "file_path": relative_path,
        "url": f"/{relative_path}",
    }
