"""
文件上传 API（上传落盘逻辑内联于此，assets 路由已删除）
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException

router = APIRouter()

# 上传文件保存目录
UPLOAD_ROOT = Path("static/uploads")

# 默认上传大小上限（20MB）
MAX_UPLOAD_SIZE = 20 * 1024 * 1024

# 扩展名白名单（content_type 可被客户端伪造，落盘前以扩展名为准）
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def save_upload(
    file: UploadFile,
    target_dir: Path,
    *,
    default_ext: str = "",
    allowed_exts: set[str] | None = None,
    max_size: int = MAX_UPLOAD_SIZE,
) -> Path:
    """保存上传文件到目标目录（uuid 唯一命名），返回落盘路径

    Args:
        file: 上传文件对象
        target_dir: 目标目录（自动创建）
        default_ext: 文件名无扩展名时的兜底扩展名
        allowed_exts: 允许的扩展名白名单（含点，小写；None 不校验）
        max_size: 文件大小上限（字节，超出拒绝）
    """
    file_ext = Path(file.filename or "").suffix.lower()
    if allowed_exts is not None and file_ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"不允许的文件类型: {file_ext or '（无扩展名）'}")

    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"{uuid.uuid4()}{file_ext or default_ext}"
    try:
        # 分块落盘并限制大小，防止超限文件写满磁盘
        written = 0
        with file_path.open("wb") as buffer:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > max_size:
                    raise HTTPException(status_code=400, detail=f"文件超过大小上限 {max_size // 1024 // 1024}MB")
                buffer.write(chunk)
    except HTTPException:
        file_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")
    finally:
        file.file.close()
    return file_path


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
