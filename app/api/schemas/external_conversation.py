
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _clean_external_source(value: str) -> str:
    source = str(value or "").strip().lower()
    if not source:
        raise ValueError("source is required")
    if len(source) > 64:
        raise ValueError("source must be 64 characters or fewer")
    allowed = set("._:-")
    if not all(ch.isalnum() or ch in allowed for ch in source):
        raise ValueError("source may only contain letters, numbers, '.', '_', ':', and '-'")
    return source


class ExternalConversationMessageIn(BaseModel):
    """A message produced by an external conversation system."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=200_000)
    source_message_id: str | None = Field(default=None, max_length=255)
    source_run_id: str | None = Field(default=None, max_length=255)
    citations: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    token_count: int | None = Field(default=None, ge=0)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        content = str(value or "").strip()
        if not content:
            raise ValueError("content is required")
        return content

    @field_validator("source_message_id", "source_run_id")
    @classmethod
    def _strip_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class ExternalConversationIngestRequest(BaseModel):
    """Import conversation turns from any external chat system into MimirQ history."""

    source: str = Field(description="External system key, e.g. dify, coze, wxwork")
    source_conversation_id: str = Field(min_length=1, max_length=255)
    conversation_id: UUID | None = Field(default=None, description="Append to an existing MimirQ conversation")
    title: str | None = Field(default=None, max_length=500)
    update_title: bool = False
    dataset_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list, max_length=500)
    source_user_id: str | None = Field(default=None, max_length=255)
    source_run_id: str | None = Field(default=None, max_length=255)
    messages: list[ExternalConversationMessageIn] = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        return _clean_external_source(value)

    @field_validator("source_conversation_id")
    @classmethod
    def _strip_source_conversation_id(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("source_conversation_id is required")
        return cleaned

    @field_validator("source_user_id", "source_run_id", "title")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class ExternalConversationIngestResponse(BaseModel):
    success: bool = True
    conversation_id: UUID
    created_conversation: bool
    source: str
    source_conversation_id: str
    inserted_messages: int
    skipped_messages: int
    message_ids: list[UUID] = Field(default_factory=list)
    skipped_source_message_ids: list[str] = Field(default_factory=list)


class ExternalConversationAsyncIngestResponse(BaseModel):
    success: bool = True
    accepted: bool = True
    queued: bool = True
    request_id: str
    source: str
    source_conversation_id: str
