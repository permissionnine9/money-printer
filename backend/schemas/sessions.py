"""
会话相关的请求和响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class SessionCreate(BaseModel):
    """创建会话请求"""
    pass  # 不需要参数，自动生成 session_id


class SessionResponse(BaseModel):
    """会话响应"""
    session_id: str
    created_at: datetime
    updated_at: datetime
    current_step: str
    status: str
    completed_steps: List[str] = Field(default_factory=list)


class SessionDetailResponse(SessionResponse):
    """会话详情响应（包含所有步骤结果）"""
    step_results: Dict[str, Any] = Field(default_factory=dict)


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[SessionResponse]
    total: int
