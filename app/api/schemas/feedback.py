"""
User feedback (evaluation loop) schemas.
"""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .base import OrmModel


class MessageFeedbackCreateRequest(BaseModel):
    """Submit/update message feedback (idempotent by tenant + message_id + account_id)."""

    message_id: UUID = Field(..., description="Assistant message ID")
    rating: int = Field(..., ge=1, le=5, description="Rating (1-5, higher is better)")
    reason: str | None = Field(default=None, description="Reason/explanation (optional)")
    tags: list[str] = Field(default_factory=list, description="Tags (optional)")
    expected_answer: str | None = Field(default=None, description="Expected answer (optional, for supervision and regression)")
    extra: dict[str, Any] = Field(default_factory=dict, description="Extension fields (optional)")


class MessageFeedbackPatchRequest(BaseModel):
    """Patch mutable feedback triage fields."""

    archived: bool | None = Field(default=None, description="Archive/unarchive the feedback item")


class MessageFeedbackOut(OrmModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    message_id: UUID
    account_id: str
    rating: int
    reason: str | None
    tags: list[str] = Field(default_factory=list)
    expected_answer: str | None
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MessageFeedbackList(BaseModel):
    total: int
    items: list[MessageFeedbackOut]


class MessageFeedbackEnrichedOut(MessageFeedbackOut):
    """Feedback with joined message/conversation context for triage UIs."""

    conversation_title: str | None = None
    message_content: str | None = None
    message_created_at: datetime | None = None


class MessageFeedbackEnrichedList(BaseModel):
    total: int
    items: list[MessageFeedbackEnrichedOut]
