"""
RAGAS regression suite schemas.

Goal: turn a fixed question set into reusable regression cases, run evaluations
across prompts/models/retrieval strategies, and persist results for iteration.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .base import OrmModel


class ReferenceSource(BaseModel):
    """A human-verified evidence pointer for a regression case."""

    document_id: UUID = Field(..., description="Evidence document id")
    chunk_id: UUID = Field(..., description="Evidence chunk id")

    # Optional audit/debug fields (best-effort; do not gate correctness).
    page_number: Optional[int] = Field(default=None, ge=1, description="1-based page number (optional)")
    start_char: Optional[int] = Field(default=None, ge=0, description="Start character offset (optional)")
    end_char: Optional[int] = Field(default=None, ge=0, description="End character offset (optional)")
    doc_pipeline_key: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Composite key `${document_id}:${pipeline_hash}` (optional, for audit/debug)",
    )
    pipeline_hash: Optional[str] = Field(default=None, max_length=64, description="Chunk pipeline hash (optional)")
    quote: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Evidence excerpt (optional; used as fallback when chunk_id becomes stale)",
    )
    label: Optional[str] = Field(default=None, max_length=100, description="Human label (optional)")


class RagasRegressionCaseCreateRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Question (user_input for regression case)")
    dataset_id: UUID = Field(..., description="Dataset ID (required; regression suite is per-dataset)")
    document_ids: List[UUID] = Field(default_factory=list, description="Document scope (optional, takes priority over dataset_id)")
    expected_answer: Optional[str] = Field(default=None, description="Expected answer (optional, for manual comparison/supervision)")
    reference_sources: List[ReferenceSource] = Field(
        ...,
        min_length=1,
        description="Human-verified evidence sources (required; at least 1). Each source must include document_id + chunk_id.",
    )
    tags: List[str] = Field(default_factory=list, description="Tags (optional)")
    extra: Dict[str, Any] = Field(default_factory=dict, description="Extension fields (optional)")


class RagasRegressionCaseOut(OrmModel):
    id: UUID
    tenant_id: UUID
    dataset_id: Optional[UUID] = None
    document_ids: List[UUID] = Field(default_factory=list)
    question: str
    expected_answer: Optional[str] = None
    reference_sources: List[ReferenceSource] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class RagasRegressionCaseList(BaseModel):
    total: int
    items: List[RagasRegressionCaseOut]


class RagasRegressionRunCreateRequest(BaseModel):
    case_ids: List[UUID] = Field(default_factory=list, description="Case IDs to run (if empty, select by filter criteria)")
    dataset_id: Optional[UUID] = Field(default=None, description="Only run cases under this dataset (optional)")
    metrics: List[str] = Field(
        default_factory=lambda: ["faithfulness", "response_relevancy"],
        description="RAGAS metrics list",
    )
    skip_empty_contexts: bool = Field(default=True, description="Skip cases without contexts (default: true)")
    max_cases: int = Field(default=50, ge=1, le=500, description="Max cases to run (default: 50)")

    # Retrieval config (aligned with chat.rag_config for comparisons).
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    retrieval_mode: str = Field(default="hybrid", description="hybrid | vector | keyword | mmr")
    alpha: float = Field(default=0.6, ge=0.0, le=1.0)
    enable_weight_rerank: bool = Field(default=True)
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)
    enable_reranker: bool = Field(default=False, description="Enable LLM reranker for re-ranking")
    reranker_provider: str = Field(default="llm", description="Reranker provider: llm | pc | none")
    reranker_top_n: int = Field(default=20, ge=1, le=200, description="Rerank candidate count (higher is slower)")

    # PromptTemplate selection (optional; for version/A-B comparison).
    prompt_template_id: Optional[UUID] = None
    prompt_template_key: Optional[str] = None
    prompt_ab_experiment_key: Optional[str] = None


class RagasRegressionRunSchema(OrmModel):
    id: UUID
    tenant_id: UUID
    account_id: Optional[str] = None
    status: str
    metrics: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class RagasRegressionItemSchema(OrmModel):
    id: UUID
    run_id: UUID
    case_id: UUID
    question: str
    response: str
    retrieved_contexts: Optional[List[str]] = None
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    scores: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RagasRegressionRunDetail(BaseModel):
    run: RagasRegressionRunSchema
    items: List[RagasRegressionItemSchema] = Field(default_factory=list)


class RagasRegressionRunList(BaseModel):
    total: int
    items: List[RagasRegressionRunSchema]
