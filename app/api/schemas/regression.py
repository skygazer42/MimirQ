"""
RAGAS regression suite schemas.

Goal: turn a fixed question set into reusable regression cases, run evaluations
across prompts/models/retrieval strategies, and persist results for iteration.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import settings
from app.rag.core.text import normalize_retrieval_mode

from .base import OrmModel

HIERARCHY_FAMILY_AGGREGATION_VALUES = ("frequency", "score", "combined")


class ReferenceSource(BaseModel):
    """A human-verified evidence pointer for a regression case."""

    document_id: UUID = Field(..., description="Evidence document id")
    chunk_id: UUID = Field(..., description="Evidence chunk id")
    chunk_index: int | None = Field(default=None, ge=0, description="0-based chunk index (optional)")
    # Optional hierarchy-aware keys (best-effort; used for family-level recall metrics).
    family_collapse_key: str | None = Field(
        default=None,
        max_length=200,
        description="Hierarchy family collapse key (optional; enables family-level recall evaluation)",
    )
    hierarchy_family_key: str | None = Field(
        default=None,
        max_length=200,
        description="Raw hierarchy family key (optional; accepted for compatibility)",
    )

    # Optional audit/debug fields (best-effort; do not gate correctness).
    page_number: int | None = Field(default=None, ge=1, description="1-based page number (optional)")
    start_char: int | None = Field(default=None, ge=0, description="Start character offset (optional)")
    end_char: int | None = Field(default=None, ge=0, description="End character offset (optional)")
    doc_pipeline_key: str | None = Field(
        default=None,
        max_length=128,
        description="Composite key `${document_id}:${pipeline_hash}` (optional, for audit/debug)",
    )
    pipeline_hash: str | None = Field(default=None, max_length=64, description="Chunk pipeline hash (optional)")
    quote: str | None = Field(
        default=None,
        max_length=2000,
        description="Evidence excerpt (optional; used as fallback when chunk_id becomes stale)",
    )
    label: str | None = Field(default=None, max_length=100, description="Human label (optional)")


class RagasRegressionCaseCreateRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Question (user_input for regression case)")
    dataset_id: UUID = Field(..., description="Dataset ID (required; regression suite is per-dataset)")
    document_ids: list[UUID] = Field(default_factory=list, description="Document scope (optional, takes priority over dataset_id)")
    expected_answer: str | None = Field(default=None, description="Expected answer (optional, for manual comparison/supervision)")
    reference_sources: list[ReferenceSource] = Field(
        ...,
        min_length=1,
        description="Human-verified evidence sources (required; at least 1). Each source must include document_id + chunk_id.",
    )
    tags: list[str] = Field(default_factory=list, description="Tags (optional)")
    reasoning_hops: list[str] = Field(
        default_factory=list,
        description="Optional multi-hop reasoning steps (ordered).",
    )
    evidence_chain: list[ReferenceSource] = Field(
        default_factory=list,
        description="Optional multi-hop evidence chain (ordered reference sources).",
    )
    extra: dict[str, Any] = Field(default_factory=dict, description="Extension fields (optional)")


class RagasRegressionCasePatchRequest(BaseModel):
    """Patch fields for an existing regression case."""

    question: str | None = Field(default=None, min_length=1)
    document_ids: list[UUID] | None = None
    expected_answer: str | None = Field(default=None, description="Set to null to clear expected_answer")
    reference_sources: list[ReferenceSource] | None = Field(default=None, min_length=1)
    tags: list[str] | None = None
    reasoning_hops: list[str] | None = None
    evidence_chain: list[ReferenceSource] | None = Field(default=None, min_length=1)
    extra: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _non_empty_patch(self):
        if not (getattr(self, "model_fields_set", None) or set()):
            raise ValueError("No fields to patch")
        return self


class RagasRegressionCaseBundleItem(BaseModel):
    """Portable regression case payload (no internal ids)."""

    question: str = Field(..., min_length=1)
    expected_answer: str | None = None
    reference_sources: list[ReferenceSource] = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    reasoning_hops: list[str] = Field(default_factory=list)
    evidence_chain: list[ReferenceSource] = Field(default_factory=list)


class RagasRegressionCaseImportRequest(BaseModel):
    """Import a dataset-scoped regression case bundle (upsert by question)."""

    dataset_id: UUID
    overwrite: bool = False
    max_items: int = Field(default=500, ge=1, le=2000)
    items: list[RagasRegressionCaseBundleItem] = Field(..., min_length=1)


class SyntheticHardcaseGenerateRequest(BaseModel):
    """
    Generate synthetic "hardcase" regression cases from an existing dataset suite.

    PII-safe defaults:
    - deterministic only (no LLM calls)
    - reuses existing reference_sources (no evidence snippets are generated)
    """

    dataset_id: UUID
    case_ids: list[UUID] = Field(default_factory=list, description="Optional base case ids (else pick by recency)")
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
    created_case_ids: list[UUID] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class RagasRegressionCaseOut(OrmModel):
    id: UUID
    tenant_id: UUID
    dataset_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list)
    question: str
    expected_answer: str | None = None
    reference_sources: list[ReferenceSource] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    reasoning_hops: list[str] = Field(default_factory=list)
    evidence_chain: list[ReferenceSource] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class RagasRegressionCaseList(BaseModel):
    total: int
    items: list[RagasRegressionCaseOut]


class RagasRegressionRunCreateRequest(BaseModel):
    case_ids: list[UUID] = Field(default_factory=list, description="Case IDs to run (if empty, select by filter criteria)")
    dataset_id: UUID = Field(..., description="Run cases under this dataset (required)")
    metrics: list[str] = Field(
        default_factory=lambda: ["faithfulness", "response_relevancy"],
        description="RAGAS metrics list",
    )
    use_llm_judge: bool = Field(
        default=False,
        description="Enable LLM-as-judge (per-case {score, reason, evidence_quotes}; adds evaluation cost)",
    )
    skip_empty_contexts: bool = Field(default=True, description="Skip cases without contexts (default: true)")
    max_cases: int = Field(default=50, ge=1, le=500, description="Max cases to run (default: 50)")

    # Retrieval config (aligned with chat.rag_config for comparisons).
    retrieval_profile: str | None = Field(
        default=None,
        description="Optional retrieval preset: recall20 | recall50 | coverage80 | hybrid_ce",
    )
    enable_query_alias_expansion: bool | None = Field(
        default=None,
        description="Enable bounded alias expansion when dataset/query aliases exist",
    )
    query_alias_max_queries: int | None = Field(default=None, ge=0, le=20)
    enable_multi_query: bool | None = Field(default=None, description="Enable bounded LLM multi-query expansion")
    multi_query_count: int | None = Field(default=None, ge=1, le=8)
    multi_query_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    multi_query_max_chars: int | None = Field(default=None, ge=0, le=2000)
    enable_hyde: bool | None = Field(default=None, description="Enable HyDE hypothetical-document query expansion")
    enable_hierarchy_recall: bool | None = Field(default=None, description="Enable hierarchy-aware recall overlay")
    hierarchy_family_collapse: bool | None = Field(default=None, description="Collapse same-family hits after recall")
    hierarchy_family_aggregation: Literal["frequency", "score", "combined"] | None = Field(
        default=None,
        description="Cross-query family aggregation strategy",
    )
    hierarchy_tree_dedup: bool | None = Field(default=None, description="Enable ancestor/child tree-style dedup")
    hierarchy_parent_depth: int | None = Field(default=None, ge=0, le=8, description="Max parent expansion depth")
    hierarchy_sibling_window: int | None = Field(default=None, ge=0, le=16, description="Max sibling expansion window")
    hierarchy_overfetch_factor: int | None = Field(default=None, ge=1, le=32, description="Overfetch multiplier before collapse")
    enable_query_rewrite: bool | None = Field(default=None, description="Enable bounded query rewrite before retrieval")
    query_rewrite_strategy: str | None = Field(default=None, description="Override query rewrite strategy id")
    query_rewrite_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    query_rewrite_max_chars: int | None = Field(default=None, ge=0, le=2000)
    sparse_retrieval_enabled: bool | None = Field(default=None, description="Enable sparse retrieval channel")
    sparse_retrieval_provider: str | None = Field(default=None, description="Sparse provider: deterministic | splade")
    # NOTE: default to 20 so retrieval-only gates can enforce Recall@20/Hit@20 without
    # requiring callers (CI scripts) to pass explicit rag_params.
    top_k: int = Field(default=20, ge=1, le=50)
    # NOTE: regression runs default to a recall-friendly threshold so retrieval-only gates
    # can enforce Hit@20/Recall@20 without requiring callers to pass rag_params.
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_mode: str = Field(default="hybrid", description="hybrid | vector | keyword | mmr")
    alpha: float = Field(default_factory=lambda: settings.RETRIEVAL_DEFAULT_ALPHA, ge=0.0, le=1.0)
    fusion_strategy: str | None = Field(default=None, description="linear | rrf | budgeted_rrf | weighted")
    fusion_budgets: dict[str, int] | None = Field(default=None)
    fusion_min_scores: dict[str, float] | None = Field(default=None)
    fusion_weights: dict[str, float] | None = Field(default=None)
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
    prompt_template_id: UUID | None = None
    prompt_template_key: str | None = None
    prompt_ab_experiment_key: str | None = None
    judge_prompt_template_id: UUID | None = None
    judge_prompt_template_key: str | None = None
    judge_prompt_ab_experiment_key: str | None = None

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def _normalize_retrieval_mode(cls, v: Any) -> str:
        return normalize_retrieval_mode(str(v) if v is not None else None)

    @field_validator("fusion_strategy", mode="before")
    @classmethod
    def _normalize_fusion_strategy(cls, v: Any) -> str | None:
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

    @field_validator("hierarchy_family_aggregation", mode="before")
    @classmethod
    def _normalize_hierarchy_family_aggregation(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError(
                "hierarchy_family_aggregation must be one of: "
                + ", ".join(HIERARCHY_FAMILY_AGGREGATION_VALUES)
            )
        raw = v.strip().lower()
        if not raw:
            return None
        if raw not in HIERARCHY_FAMILY_AGGREGATION_VALUES:
            raise ValueError(
                "hierarchy_family_aggregation must be one of: "
                + ", ".join(HIERARCHY_FAMILY_AGGREGATION_VALUES)
            )
        return raw

    @field_validator("query_rewrite_strategy", mode="before")
    @classmethod
    def _normalize_query_rewrite_strategy(cls, v: Any) -> str | None:
        raw = str(v or "").strip()
        return raw or None

    @field_validator("sparse_retrieval_provider", mode="before")
    @classmethod
    def _normalize_sparse_retrieval_provider(cls, v: Any) -> str | None:
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


class RagasRegressionAblationBatchRequest(RagasRegressionRunCreateRequest):
    grid: dict[str, list[Any]] = Field(
        ...,
        min_length=1,
        description="Ablation parameter grid; values are cartesian-expanded into regression runs",
    )
    max_combinations: int = Field(default=50, ge=1, le=200, description="Safety cap for expanded variants")
    ablation_label_prefix: str | None = Field(default=None, max_length=80)


class RagasRegressionAblationBatchResponse(BaseModel):
    ablation_id: UUID
    total: int
    run_ids: list[UUID] = Field(default_factory=list)
    variants: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "queued"


class RagasRegressionRunSchema(OrmModel):
    id: UUID
    tenant_id: UUID
    account_id: str | None = None
    dataset_id: UUID | None = None
    status: str
    metrics: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RagasRegressionItemSchema(OrmModel):
    id: UUID
    run_id: UUID
    case_id: UUID
    question: str
    response: str
    retrieved_contexts: list[str] | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    scores: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RagasRegressionRunDetail(BaseModel):
    run: RagasRegressionRunSchema
    items: list[RagasRegressionItemSchema] = Field(default_factory=list)


class RagasRegressionRunList(BaseModel):
    total: int
    items: list[RagasRegressionRunSchema]


class RagasRegressionRunLeaderboardItem(BaseModel):
    run_id: UUID
    status: str
    created_at: datetime | None = None
    finished_at: datetime | None = None
    metric_key: str
    metric_value: float | None = None
    retrieval_config_hash: str | None = None


class RagasRegressionRunLeaderboardResponse(BaseModel):
    metric_key: str
    items: list[RagasRegressionRunLeaderboardItem] = Field(default_factory=list)


class RegressionRunMetricDiff(BaseModel):
    key: str
    before: Any = None
    after: Any = None
    delta: float | None = None


class RegressionRunDiffScore(BaseModel):
    """
    Compact score payload for CI / dashboards.

    Notes:
    - This is intentionally a small, stable schema (PII-safe numeric aggregates only).
    - `weights` are the effective normalized weights applied to the `used_metric_keys` set.
    """

    version: str = "1"
    used_metric_keys: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)

    base_score: float | None = None
    target_score: float | None = None
    delta: float | None = None

    base_metrics: dict[str, float] = Field(default_factory=dict)
    target_metrics: dict[str, float] = Field(default_factory=dict)


class RegressionRunSliceBucketDiff(BaseModel):
    key: str
    items_before: int = 0
    items_after: int = 0
    metrics: list[RegressionRunMetricDiff] = Field(default_factory=list)


class RegressionRunSliceDiff(BaseModel):
    truncated_before: bool = False
    truncated_after: bool = False
    buckets: list[RegressionRunSliceBucketDiff] = Field(default_factory=list)


class RegressionRunCaseDiff(BaseModel):
    case_id: str
    question: str = ""
    metric_diffs: list[RegressionRunMetricDiff] = Field(default_factory=list)
    mean_delta: float | None = None
    label: str = "无分数"


class RegressionRunMetricSignificance(BaseModel):
    key: str
    compared: int = 0
    base_mean: float | None = None
    target_mean: float | None = None
    delta_mean: float | None = None
    bootstrap_ci_low: float | None = None
    bootstrap_ci_high: float | None = None
    p_value: float | None = None
    p_value_method: str | None = None
    p_value_bh: float | None = None
    wilcoxon_p_value: float | None = None
    mcnemar_p_value: float | None = None
    cohen_d: float | None = None
    significant: bool = False


class RagasRegressionRunDiffResponse(BaseModel):
    base_run_id: UUID
    target_run_id: UUID
    generated_at: datetime
    base_params: dict[str, Any] = Field(default_factory=dict)
    target_params: dict[str, Any] = Field(default_factory=dict)
    metric_diffs: list[RegressionRunMetricDiff] = Field(default_factory=list)
    diff_score: RegressionRunDiffScore | None = None
    slice_diffs: dict[str, RegressionRunSliceDiff] = Field(default_factory=dict)
    significance: list[RegressionRunMetricSignificance] = Field(default_factory=list)
    case_diffs: list[RegressionRunCaseDiff] = Field(default_factory=list)
    significance_summary: dict[str, Any] = Field(default_factory=dict)
