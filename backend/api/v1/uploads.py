"""
文件上传 API
"""
from fastapi import APIRouter, File, UploadFile, HTTPException
from pathlib import Path
import uuid
import shutil

router = APIRouter()

# 上传文件保存目录
UPLOAD_DIR = Path("static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
    """上传图片文件"""
    # 验证文件类型
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="只能上传图片文件")
    
    # 生成唯一文件名
    file_ext = Path(file.filename).suffix
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    
    # 保存文件
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")
    finally:
        file.file.close()
    
    # 返回文件路径（相对路径）
    relative_path = f"static/uploads/{unique_filename}"
    
    return {
        "success": True,
        "message": "文件上传成功",
        "file_path": relative_path,
        "url": f"/{relative_path}",
    }
