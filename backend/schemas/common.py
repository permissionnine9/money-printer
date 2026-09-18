"""通用响应包络（新路由统一使用，存量路由渐进迁移）"""
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应包络 {"success": bool, "data": ..., "message": ...}"""
    success: bool = True
    data: Optional[T] = None
    message: Optional[str] = None
