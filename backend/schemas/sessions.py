"""
会话相关的请求和响应模型
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class SessionResponse(BaseModel):
    """会话响应"""
    session_id: str
    created_at: datetime
    updated_at: datetime
    current_step: Optional[str] = None  # 完成所有步骤后可能为 None
    status: str
    completed_steps: List[str] = Field(default_factory=list)
    legacy: bool = Field(default=False, description="旧版 7 步会话（不兼容新工作流）")


class SessionDetailResponse(SessionResponse):
    """会话详情响应（包含所有步骤结果）"""
    step_results: Dict[str, Any] = Field(default_factory=dict)


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[SessionResponse]
    total: int
