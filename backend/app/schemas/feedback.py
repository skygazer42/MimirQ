"""
用户反馈（评测闭环）相关 Schema。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MessageFeedbackCreateRequest(BaseModel):
    """提交/更新一条消息反馈（按 tenant + message_id + account_id 幂等）。"""

    message_id: UUID = Field(..., description="assistant 消息 ID")
    rating: int = Field(..., ge=1, le=5, description="评分（1~5，越高越好）")
    reason: Optional[str] = Field(default=None, description="原因/说明（可选）")
    tags: List[str] = Field(default_factory=list, description="标签（可选）")
    expected_answer: Optional[str] = Field(default=None, description="期望答案（可选，用于监督与回归）")
    extra: Dict[str, Any] = Field(default_factory=dict, description="扩展字段（可选）")


class MessageFeedbackOut(BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    message_id: UUID
    account_id: str
    rating: int
    reason: Optional[str]
    tags: List[str] = []
    expected_answer: Optional[str]
    extra: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageFeedbackList(BaseModel):
    total: int
    items: List[MessageFeedbackOut]

