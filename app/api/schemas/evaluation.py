"""
RAGAS evaluation schemas.

Defines data models for evaluation tasks and results.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from .base import OrmModel


class RagasRunCreateRequest(BaseModel):
    """Create a RAGAS evaluation run for a conversation."""

    conversation_id: UUID = Field(..., description="Conversation ID to evaluate")
    metrics: List[str] = Field(
        default_factory=lambda: ["faithfulness", "response_relevancy"],
        description="Evaluation metrics list (default: faithfulness, response_relevancy)",
    )
    max_turns: int = Field(default=20, ge=1, le=200, description="Max recent N turns to evaluate")
    skip_empty_contexts: bool = Field(default=True, description="Skip turns without citations/contexts")
    include_contexts_in_response: bool = Field(default=False, description="Include contexts in detail response (may be large)")


class RagasRunSchema(OrmModel):
    """Evaluation run metadata."""

    id: UUID
    conversation_id: Optional[UUID] = None
    status: str
    metrics: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class RagasItemSchema(OrmModel):
    """Per-turn evaluation item."""

    id: UUID
    run_id: UUID
    turn_index: int
    user_message_id: Optional[UUID] = None
    assistant_message_id: Optional[UUID] = None
    user_input: str
    response: str
    retrieved_contexts: Optional[List[str]] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    scores: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RagasRunDetail(BaseModel):
    run: RagasRunSchema
    items: List[RagasItemSchema] = Field(default_factory=list)


class RagasRunList(BaseModel):
    total: int
    items: List[RagasRunSchema]


# ==================== Test question generation schemas ====================


class TestGenFromDocsRequest(BaseModel):
    """Request to generate test questions from documents."""

    dataset_id: Optional[UUID] = Field(default=None, description="Dataset ID (optional)")
    document_ids: List[UUID] = Field(default_factory=list, description="Document ID list (takes priority over dataset_id)")
    num_questions: int = Field(default=10, ge=1, le=50, description="Number of questions to generate")
    question_types: List[str] = Field(
        default_factory=lambda: ["factual", "reasoning", "comparison"],
        description="Question types: factual, reasoning, comparison"
    )
    auto_save_as_cases: bool = Field(default=True, description="Auto-save as regression test cases")


class TestGenFromConversationsRequest(BaseModel):
    """Request to generate test questions from conversation history."""

    conversation_ids: List[UUID] = Field(..., min_length=1, description="Conversation ID list")
    num_questions: int = Field(default=10, ge=1, le=50, description="Number of questions to generate")
    quality_threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Quality threshold")
    auto_save_as_cases: bool = Field(default=True, description="Auto-save as regression test cases")


class GeneratedQuestion(BaseModel):
    """Generated question."""

    question: str = Field(..., description="Question content")
    expected_answer: Optional[str] = Field(default=None, description="Expected answer")
    context: Optional[str] = Field(default=None, description="Question source context")
    source_type: str = Field(..., description="Source type: document or conversation")
    source_id: str = Field(..., description="Source ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class TestGenResponse(BaseModel):
    """Test question generation response."""

    status: str = Field(..., description="Status: completed or failed")
    generated_questions: List[GeneratedQuestion] = Field(default_factory=list, description="Generated questions list")
    saved_case_ids: List[UUID] = Field(default_factory=list, description="IDs of saved cases")
    error_message: Optional[str] = Field(default=None, description="Error message (if failed)")
