"""
RAGAS evaluation schemas.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RagasRunCreateRequest(BaseModel):
    """Create a RAGAS evaluation run for a conversation."""

    conversation_id: UUID = Field(..., description="要评测的对话 ID")
    metrics: List[str] = Field(
        default_factory=lambda: ["faithfulness", "response_relevancy"],
        description="评测指标列表（默认: faithfulness, response_relevancy）",
    )
    max_turns: int = Field(default=20, ge=1, le=200, description="最多评测最近 N 轮问答")
    skip_empty_contexts: bool = Field(default=True, description="跳过没有引用/上下文的轮次")
    include_contexts_in_response: bool = Field(default=False, description="在明细中返回 contexts（可能较大）")


class RagasRunSchema(BaseModel):
    """Evaluation run metadata."""

    id: UUID
    conversation_id: Optional[UUID] = None
    status: str
    metrics: List[str] = []
    params: Dict[str, Any] = {}
    summary: Dict[str, Any] = {}
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RagasItemSchema(BaseModel):
    """Per-turn evaluation item."""

    id: UUID
    run_id: UUID
    turn_index: int
    user_message_id: Optional[UUID] = None
    assistant_message_id: Optional[UUID] = None
    user_input: str
    response: str
    retrieved_contexts: Optional[List[str]] = None
    citations: List[Dict[str, Any]] = []
    scores: Dict[str, Any] = {}
    created_at: datetime

    class Config:
        from_attributes = True


class RagasRunDetail(BaseModel):
    run: RagasRunSchema
    items: List[RagasItemSchema] = []


class RagasRunList(BaseModel):
    total: int
    items: List[RagasRunSchema]
