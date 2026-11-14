"""Dify external knowledge and conversation API contracts."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.config import settings


class DifyRetrievalSetting(BaseModel):
    top_k: int = Field(default=5, ge=1, le=200)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_profile: str | None = Field(default=None, max_length=32)
    enable_kg_query_expansion: bool | None = None
    enable_kg_chunk_injection: bool | None = None
    kg_chunk_injection_max_chunks: int | None = Field(default=None, ge=0, le=50)
    enable_kg_chunk_boost: bool | None = None
    kg_chunk_boost_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    kg_chunk_boost_max_promoted: int | None = Field(default=None, ge=0, le=20)


class DifyExternalKnowledgeRequest(BaseModel):
    knowledge_id: str = Field(min_length=1)
    query: str = Field(min_length=1, max_length=settings.RETRIEVAL_QUERY_MAX_CHARS)
    retrieval_setting: DifyRetrievalSetting = Field(default_factory=DifyRetrievalSetting)
    metadata_condition: dict[str, Any] | None = None
    conversation_id: UUID | str | None = None
    request_id: str | None = Field(default=None, min_length=1, max_length=200)
    source_conversation_id: str | None = Field(default=None, max_length=255)
    source_message_id: str | None = Field(default=None, max_length=255)
    source_run_id: str | None = Field(default=None, max_length=255)
    dify_conversation_id: str | None = Field(default=None, max_length=255)
    dify_message_id: str | None = Field(default=None, max_length=200)
    dify_workflow_run_id: str | None = Field(default=None, max_length=200)


class DifyExternalKnowledgeRecord(BaseModel):
    content: str
    score: float
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DifyExternalKnowledgeResponse(BaseModel):
    records: list[DifyExternalKnowledgeRecord]


class DifyConversationTurnRequest(BaseModel):
    query: str = Field(min_length=1, max_length=settings.RETRIEVAL_QUERY_MAX_CHARS)
    answer: str = Field(min_length=1)
    conversation_id: UUID | str | None = None
    trace_request_id: str | None = Field(default=None, max_length=200)
    source_conversation_id: str | None = Field(default=None, max_length=255)
    source_message_id: str | None = Field(default=None, max_length=255)
    source_run_id: str | None = Field(default=None, max_length=255)
    dify_conversation_id: str | None = Field(default=None, max_length=255)
    dify_message_id: str | None = Field(default=None, max_length=200)
    dify_workflow_run_id: str | None = Field(default=None, max_length=200)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DifyConversationTurnResponse(BaseModel):
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    reused_user_message: bool
