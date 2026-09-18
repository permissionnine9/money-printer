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
    script_session_id: Optional[str] = Field(default="", description="引用的剧本会话ID（未完成选集为空）")
    script_title: Optional[str] = Field(default="", description="引用的剧本会话名称")
    episode_title: Optional[str] = Field(default="", description="引用的分集名称")
    episode_number: Optional[int] = Field(default=None, description="集数（从 episode_id 解析，如 ep_01 → 1）")


class SessionDetailResponse(SessionResponse):
    """会话详情响应（包含所有步骤结果）"""
    step_results: Dict[str, Any] = Field(default_factory=dict)


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[SessionResponse]
    total: int
