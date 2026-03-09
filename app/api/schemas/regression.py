"""
RAGAS regression suite schemas.

Goal: turn a fixed question set into reusable regression cases, run evaluations
across prompts/models/retrieval strategies, and persist results for iteration.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings
from app.rag.core.text import normalize_retrieval_mode

from .base import OrmModel


class ReferenceSource(BaseModel):
    """A human-verified evidence pointer for a regression case."""

    document_id: UUID = Field(..., description="Evidence document id")
    chunk_id: UUID = Field(..., description="Evidence chunk id")
    chunk_index: Optional[int] = Field(default=None, ge=0, description="0-based chunk index (optional)")

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


class RagasRegressionCasePatchRequest(BaseModel):
    """Patch fields for an existing regression case."""

    question: Optional[str] = Field(default=None, min_length=1)
    document_ids: Optional[List[UUID]] = None
    expected_answer: Optional[str] = Field(default=None, description="Set to null to clear expected_answer")
    reference_sources: Optional[List[ReferenceSource]] = Field(default=None, min_length=1)
    tags: Optional[List[str]] = None
    extra: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _non_empty_patch(self):
        if not (getattr(self, "model_fields_set", None) or set()):
            raise ValueError("No fields to patch")
        return self


class RagasRegressionCaseBundleItem(BaseModel):
    """Portable regression case payload (no internal ids)."""

    question: str = Field(..., min_length=1)
    expected_answer: Optional[str] = None
    reference_sources: List[ReferenceSource] = Field(..., min_length=1)
    tags: List[str] = Field(default_factory=list)


class RagasRegressionCaseImportRequest(BaseModel):
    """Import a dataset-scoped regression case bundle (upsert by question)."""

    dataset_id: UUID
    overwrite: bool = False
    max_items: int = Field(default=500, ge=1, le=2000)
    items: List[RagasRegressionCaseBundleItem] = Field(..., min_length=1)


class SyntheticHardcaseGenerateRequest(BaseModel):
    """
    Generate synthetic "hardcase" regression cases from an existing dataset suite.

    PII-safe defaults:
    - deterministic only (no LLM calls)
    - reuses existing reference_sources (no evidence snippets are generated)
    """

    dataset_id: UUID
    case_ids: List[UUID] = Field(default_factory=list, description="Optional base case ids (else pick by recency)")
    max_cases: int = Field(default=50, ge=1, le=200, description="Max base cases to use")
    hardcases_per_case: int = Field(default=4, ge=0, le=20, description="Max synthetic hardcases per base case")
    max_created: int = Field(default=500, ge=0, le=5000, description="Global cap on created cases")
    mode: Literal["deterministic"] = Field(default="deterministic")
    dry_run: bool = Field(default=False, description="Plan only; do not persist new cases")
    tag: str = Field(default="synthetic_hardcase", max_length=64, description="Tag to add to created cases")


class SyntheticHardcaseGenerateResponse(BaseModel):
    dataset_id: UUID
    base_cases_total: int = 0
    base_cases_evaluated: int = 0
    hardcases_generated: int = 0
    created: int = 0
    skipped_duplicates: int = 0
    created_case_ids: List[UUID] = Field(default_factory=list)
    errors: List[Dict[str, Any]] = Field(default_factory=list)


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
    dataset_id: UUID = Field(..., description="Run cases under this dataset (required)")
    metrics: List[str] = Field(
        default_factory=lambda: ["faithfulness", "response_relevancy"],
        description="RAGAS metrics list",
    )
    skip_empty_contexts: bool = Field(default=True, description="Skip cases without contexts (default: true)")
    max_cases: int = Field(default=50, ge=1, le=500, description="Max cases to run (default: 50)")

    # Retrieval config (aligned with chat.rag_config for comparisons).
    retrieval_profile: Optional[str] = Field(
        default=None,
        description="Optional retrieval preset: recall20 | recall50 | coverage80 | hybrid_ce",
    )
    enable_query_alias_expansion: Optional[bool] = Field(
        default=None,
        description="Enable bounded alias expansion when dataset/query aliases exist",
    )
    query_alias_max_queries: Optional[int] = Field(default=None, ge=0, le=20)
    enable_multi_query: Optional[bool] = Field(default=None, description="Enable bounded LLM multi-query expansion")
    multi_query_count: Optional[int] = Field(default=None, ge=1, le=8)
    multi_query_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    multi_query_max_chars: Optional[int] = Field(default=None, ge=0, le=2000)
    enable_query_rewrite: Optional[bool] = Field(default=None, description="Enable bounded query rewrite before retrieval")
    query_rewrite_strategy: Optional[str] = Field(default=None, description="Override query rewrite strategy id")
    query_rewrite_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    query_rewrite_max_chars: Optional[int] = Field(default=None, ge=0, le=2000)
    sparse_retrieval_enabled: Optional[bool] = Field(default=None, description="Enable sparse retrieval channel")
    sparse_retrieval_provider: Optional[str] = Field(default=None, description="Sparse provider: deterministic | splade")
    # NOTE: default to 20 so retrieval-only gates can enforce Recall@20/Hit@20 without
    # requiring callers (CI scripts) to pass explicit rag_params.
    top_k: int = Field(default=20, ge=1, le=50)
    # NOTE: regression runs default to a recall-friendly threshold so retrieval-only gates
    # can enforce Hit@20/Recall@20 without requiring callers to pass rag_params.
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_mode: str = Field(default="hybrid", description="hybrid | vector | keyword | mmr")
    alpha: float = Field(default=0.6, ge=0.0, le=1.0)
    fusion_strategy: Optional[str] = Field(default=None, description="linear | rrf | budgeted_rrf | weighted")
    fusion_budgets: Optional[Dict[str, int]] = Field(default=None)
    fusion_min_scores: Optional[Dict[str, float]] = Field(default=None)
    fusion_weights: Optional[Dict[str, float]] = Field(default=None)
    enable_weight_rerank: bool = Field(default=True)
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)
    # Default to the server runtime so regression gates can mirror the real retrieval path
    # without requiring every caller to restate reranker flags explicitly.
    enable_reranker: bool = Field(
        default_factory=lambda: settings.ENABLE_RERANKER,
        description="Enable reranker for re-ranking",
    )
    reranker_provider: str = Field(
        default_factory=lambda: settings.RERANKER_PROVIDER,
        description="Reranker provider: llm | pc | ltr | colbert | cross_encoder | none",
    )
    reranker_top_n: int = Field(
        default_factory=lambda: settings.RERANKER_TOP_N,
        ge=1,
        le=200,
        description="Rerank candidate count (higher is slower)",
    )

    # PromptTemplate selection (optional; for version/A-B comparison).
    prompt_template_id: Optional[UUID] = None
    prompt_template_key: Optional[str] = None
    prompt_ab_experiment_key: Optional[str] = None

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def _normalize_retrieval_mode(cls, v: Any) -> str:
        return normalize_retrieval_mode(str(v) if v is not None else None)

    @field_validator("fusion_strategy", mode="before")
    @classmethod
    def _normalize_fusion_strategy(cls, v: Any) -> Optional[str]:
        raw = str(v or "").strip().lower()
        if not raw:
            return None
        if raw in {"reciprocal_rank_fusion", "rrf"}:
            return "rrf"
        if raw in {"budget_rrf", "budgeted_rrf"}:
            return "budgeted_rrf"
        if raw in {"weighted", "weighted_linear", "weighted_sum"}:
            return "weighted"
        if raw == "linear":
            return "linear"
        raise ValueError("fusion_strategy must be one of: linear, rrf, budgeted_rrf, weighted")

    @field_validator("query_rewrite_strategy", mode="before")
    @classmethod
    def _normalize_query_rewrite_strategy(cls, v: Any) -> Optional[str]:
        raw = str(v or "").strip()
        return raw or None

    @field_validator("sparse_retrieval_provider", mode="before")
    @classmethod
    def _normalize_sparse_retrieval_provider(cls, v: Any) -> Optional[str]:
        raw = str(v or "").strip().lower()
        if not raw:
            return None
        if raw not in {"deterministic", "splade"}:
            raise ValueError("sparse_retrieval_provider must be one of: deterministic, splade")
        return raw

    @model_validator(mode="after")
    def _validate_fusion_overrides(self):
        allowed = {"vector", "bm25", "lexical", "sparse"}

        if self.fusion_budgets is not None:
            if not isinstance(self.fusion_budgets, dict):
                raise ValueError("fusion_budgets must be an object")
            bad = [str(k) for k in self.fusion_budgets.keys() if str(k) not in allowed]
            if bad:
                raise ValueError(f"fusion_budgets keys must be among: {sorted(allowed)}")
            for value in self.fusion_budgets.values():
                iv = int(value)
                if iv < 0 or iv > 1000:
                    raise ValueError("fusion_budgets values must be in [0,1000]")

        if self.fusion_min_scores is not None:
            if not isinstance(self.fusion_min_scores, dict):
                raise ValueError("fusion_min_scores must be an object")
            bad = [str(k) for k in self.fusion_min_scores.keys() if str(k) not in allowed]
            if bad:
                raise ValueError(f"fusion_min_scores keys must be among: {sorted(allowed)}")
            for value in self.fusion_min_scores.values():
                fv = float(value)
                if fv < 0.0 or fv > 1.0:
                    raise ValueError("fusion_min_scores values must be in [0,1]")

        if self.fusion_weights is not None:
            if not isinstance(self.fusion_weights, dict):
                raise ValueError("fusion_weights must be an object")
            bad = [str(k) for k in self.fusion_weights.keys() if str(k) not in allowed]
            if bad:
                raise ValueError(f"fusion_weights keys must be among: {sorted(allowed)}")
            for value in self.fusion_weights.values():
                fv = float(value)
                if fv < 0.0 or fv > 10.0:
                    raise ValueError("fusion_weights values must be in [0,10]")

        return self


class RagasRegressionRunSchema(OrmModel):
    id: UUID
    tenant_id: UUID
    account_id: Optional[str] = None
    dataset_id: Optional[UUID] = None
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


class RagasRegressionRunLeaderboardItem(BaseModel):
    run_id: UUID
    status: str
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    metric_key: str
    metric_value: Optional[float] = None
    retrieval_config_hash: Optional[str] = None


class RagasRegressionRunLeaderboardResponse(BaseModel):
    metric_key: str
    items: List[RagasRegressionRunLeaderboardItem] = Field(default_factory=list)


class RegressionRunMetricDiff(BaseModel):
    key: str
    before: Any = None
    after: Any = None
    delta: Optional[float] = None


class RegressionRunDiffScore(BaseModel):
    """
    Compact score payload for CI / dashboards.

    Notes:
    - This is intentionally a small, stable schema (PII-safe numeric aggregates only).
    - `weights` are the effective normalized weights applied to the `used_metric_keys` set.
    """

    version: str = "1"
    used_metric_keys: List[str] = Field(default_factory=list)
    weights: Dict[str, float] = Field(default_factory=dict)

    base_score: Optional[float] = None
    target_score: Optional[float] = None
    delta: Optional[float] = None

    base_metrics: Dict[str, float] = Field(default_factory=dict)
    target_metrics: Dict[str, float] = Field(default_factory=dict)


class RegressionRunSliceBucketDiff(BaseModel):
    key: str
    items_before: int = 0
    items_after: int = 0
    metrics: List[RegressionRunMetricDiff] = Field(default_factory=list)


class RegressionRunSliceDiff(BaseModel):
    truncated_before: bool = False
    truncated_after: bool = False
    buckets: List[RegressionRunSliceBucketDiff] = Field(default_factory=list)


class RagasRegressionRunDiffResponse(BaseModel):
    base_run_id: UUID
    target_run_id: UUID
    generated_at: datetime
    base_params: Dict[str, Any] = Field(default_factory=dict)
    target_params: Dict[str, Any] = Field(default_factory=dict)
    metric_diffs: List[RegressionRunMetricDiff] = Field(default_factory=list)
    diff_score: Optional[RegressionRunDiffScore] = None
    slice_diffs: Dict[str, RegressionRunSliceDiff] = Field(default_factory=dict)
