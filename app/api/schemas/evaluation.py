"""
RAGAS evaluation schemas.

Defines data models for evaluation tasks and results.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .base import OrmModel


class RagasRunCreateRequest(BaseModel):
    """Create a RAGAS evaluation run for a conversation."""

    conversation_id: UUID = Field(..., description="Conversation ID to evaluate")
    metrics: list[str] = Field(
        default_factory=lambda: ["faithfulness", "response_relevancy"],
        description="Evaluation metrics list (default: faithfulness, response_relevancy)",
    )
    max_turns: int = Field(default=20, ge=1, le=200, description="Max recent N turns to evaluate")
    skip_empty_contexts: bool = Field(default=True, description="Skip turns without citations/contexts")
    include_contexts_in_response: bool = Field(
        default=False, description="Include contexts in detail response (may be large)"
    )


class RagasRunSchema(OrmModel):
    """Evaluation run metadata."""

    id: UUID
    conversation_id: UUID | None = None
    status: str
    metrics: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RagasItemSchema(OrmModel):
    """Per-turn evaluation item."""

    id: UUID
    run_id: UUID
    turn_index: int
    user_message_id: UUID | None = None
    assistant_message_id: UUID | None = None
    user_input: str
    response: str
    retrieved_contexts: list[str] | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    scores: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RagasRunDetail(BaseModel):
    run: RagasRunSchema
    items: list[RagasItemSchema] = Field(default_factory=list)


class RagasRunList(BaseModel):
    total: int
    items: list[RagasRunSchema]


class RagasConversationReadinessRequest(BaseModel):
    """Batch request for conversation evaluation readiness."""

    conversation_ids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Conversation IDs to inspect for citation-backed RAGAS evaluation",
    )


class RagasConversationReadinessItem(BaseModel):
    """Citation-backed evaluation readiness for one conversation."""

    conversation_id: UUID
    assistant_turns: int = 0
    evaluable_turns: int = 0
    citations_count: int = 0
    is_evaluable: bool = False


class RagasConversationReadinessResponse(BaseModel):
    total: int
    items: list[RagasConversationReadinessItem]


# ==================== Test question generation schemas ====================


class TestGenFromDocsRequest(BaseModel):
    """Request to generate test questions from documents."""

    dataset_id: UUID | None = Field(default=None, description="Dataset ID (optional)")
    document_ids: list[UUID] = Field(
        default_factory=list, description="Document ID list (takes priority over dataset_id)"
    )
    num_questions: int = Field(default=10, ge=1, le=50, description="Number of questions to generate")
    question_types: list[str] = Field(
        default_factory=lambda: ["factual", "multi_hop", "comparison"],
        description=(
            "Question types: factual, multi_hop (reasoning), comparison, conditional, unanswerable. "
            "Back-compat: 'reasoning' is treated as 'multi_hop'."
        ),
    )
    auto_save_as_cases: bool = Field(default=True, description="Auto-save as regression test cases")
    prompt_template_id: UUID | None = Field(
        default=None, description="Optional prompt template id for document test generation"
    )
    prompt_template_key: str | None = Field(
        default=None, description="Optional prompt template key for latest active version"
    )
    prompt_ab_experiment_key: str | None = Field(
        default=None, description="Optional A/B experiment key for prompt selection"
    )


class TestGenFromConversationsRequest(BaseModel):
    """Request to generate test questions from conversation history."""

    conversation_ids: list[UUID] = Field(..., min_length=1, description="Conversation ID list")
    num_questions: int = Field(default=10, ge=1, le=50, description="Number of questions to generate")
    quality_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Quality threshold")
    auto_save_as_cases: bool = Field(default=True, description="Auto-save as regression test cases")


class GeneratedQuestion(BaseModel):
    """Generated question."""

    question: str = Field(..., description="Question content")
    expected_answer: str | None = Field(default=None, description="Expected answer")
    context: str | None = Field(default=None, description="Question source context")
    source_type: str = Field(..., description="Source type: document or conversation")
    source_id: str = Field(..., description="Source ID")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class TestGenResponse(BaseModel):
    """Test question generation response."""

    status: str = Field(..., description="Status: completed or failed")
    generated_questions: list[GeneratedQuestion] = Field(default_factory=list, description="Generated questions list")
    saved_case_ids: list[UUID] = Field(default_factory=list, description="IDs of saved cases")
    error_message: str | None = Field(default=None, description="Error message (if failed)")
