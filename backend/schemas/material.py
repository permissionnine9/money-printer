"""素材管理请求 schema"""
from pydantic import BaseModel, Field


class MaterialFilesDeleteRequest(BaseModel):
    """批量删除素材文件请求（孤儿清理 / 上传图与视频单删入口）"""
    paths: list[str] = Field(..., description="素材文件相对路径列表（static/{images,videos,uploads} 内）")
