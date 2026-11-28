"""
User feedback (evaluation loop) schemas.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.base import OrmModel

FeedbackCategory = Literal["retrieval_miss", "wrong_answer", "out_of_scope", "other"]
FeedbackCategorySource = Literal["user", "llm_auto", "reviewer"]


class MessageFeedbackCreateRequest(BaseModel):
    """Submit/update message feedback (idempotent by tenant + message_id + account_id)."""

    message_id: UUID = Field(description="Assistant message ID")
    rating: int = Field(ge=1, le=5, description="Rating (1-5, higher is better)")
    reason: str | None = Field(default=None, description="Reason/explanation (optional)")
    tags: list[str] = Field(default_factory=list, description="Tags (optional)")
    expected_answer: str | None = Field(
        default=None, description="Expected answer (optional, for supervision and regression)"
    )
    category: FeedbackCategory | None = Field(default=None, description="Negative-feedback root cause (optional)")
    extra: dict[str, Any] = Field(default_factory=dict, description="Extension fields (optional)")


class MessageFeedbackPatchRequest(BaseModel):
    """Patch mutable feedback triage fields."""

    archived: bool | None = Field(default=None, description="Archive/unarchive the feedback item")
    category: FeedbackCategory | None = Field(default=None, description="Reviewer-assigned root cause")


class MessageFeedbackListQuery(BaseModel):
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    min_rating: int | None = None
    max_rating: int | None = None


class FeedbackLoopCandidatesQuery(BaseModel):
    max_rating: int = Field(default=2, ge=1, le=5)
    limit: int = Field(default=200, ge=1, le=1000)
    ruleset: str | None = None


class FeedbackLoopExportQuery(FeedbackLoopCandidatesQuery):
    dry_run: bool = True
    append: bool = True


class FeedbackToRegressionCaseRequest(BaseModel):
    include_document_scope: bool = True
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class FeedbackToEvidenceItemRequest(BaseModel):
    suite_id: UUID
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class FeedbackLoopSummary(BaseModel):
    feedback_total: int
    negative_feedback_total: int
    hard_negative_records: int
    training_triples: int
    eval_case_candidates: int
    rules_glossary_candidates: int
    rules_pattern_candidates: int
    rules_intent_candidates: int


class FeedbackLoopRulesSuggestions(BaseModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    ruleset: str | None
    glossary_suggestions: list[dict[str, Any]]
    pattern_suggestions: list[dict[str, Any]]
    intent_suggestions: list[dict[str, Any]]


class FeedbackLoopCandidatesResponse(BaseModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    summary: FeedbackLoopSummary
    hard_negative_records: list[dict[str, Any]]
    training_triples: list[dict[str, Any]]
    eval_case_candidates: list[dict[str, Any]]
    rules_suggestions: FeedbackLoopRulesSuggestions


class FeedbackLoopHardNegativeExport(BaseModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    output_path: str
    append: bool
    dry_run: bool
    candidate_records: int
    written_records: int
    hard_negatives: int
    source_feedback_ids: list[str]
    dataset_ids: list[str]


class FeedbackLoopExportResponse(BaseModel):
    schema_: str = Field(alias="schema", serialization_alias="schema")
    trigger: str
    realtime_listener_enabled: bool
    dry_run: bool
    candidates: FeedbackLoopSummary
    eval_case_candidates: list[dict[str, Any]]
    hard_negative_export: FeedbackLoopHardNegativeExport
    rules_suggestions: FeedbackLoopRulesSuggestions


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
    category: FeedbackCategory | None = None
    category_source: FeedbackCategorySource | None = None
    query_hash: str | None = None
    retrieval_trace_ref: str | None = None
    profile: str | None = None
    judge_score_ref: str | None = None
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
