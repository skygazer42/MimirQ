"""
Dataset-related Pydantic schemas.
Defines data models for dataset creation, update, and query endpoints.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas.base import OrmModel
from app.api.schemas.documents import DocumentPipelineOptions
from app.api.schemas.identity import FlsPolicy
from app.api.schemas.sources import IngestionPolicy
from app.core.model_execution import reject_retired_provider, validate_rag_execution_selection
from app.models.dataset import DatasetPermissionEnum
from app.rag.core.retrieval_modes import normalize_retrieval_mode
from app.rag.retrieval.contract import (
    VALID_RETRIEVAL_CONTRACT_MODES,
    normalize_retrieval_contract_mode,
)

HIERARCHY_FAMILY_AGGREGATION_VALUES = ("frequency", "score", "combined")
FUSION_CHANNELS = {"vector", "bm25", "lexical", "sparse"}


def _validate_fusion_map_keys(raw: dict[str, Any] | None, *, field_name: str) -> None:
    if raw is None:
        return
    for key in (k.strip().lower() for k in raw):
        if key and key not in FUSION_CHANNELS:
            raise ValueError(f"{field_name} keys must be one of: vector, bm25, lexical, sparse")


class DatasetChunkTargetsV2(BaseModel):
    """
    Per-dataset chunk target distribution spec (v2).

    This is used by:
    - Dataset profile "chunk_targets" checks (objective signals + suggestions)
    - Chunking auto-tune tooling (search chunk_strategy/size/overlap)

    Notes:
    - This is intentionally small and declarative.
    - Values are "best-effort" targets; they do not directly change ingestion behavior.
    """

    model_config = ConfigDict(extra="ignore")

    # Token distribution objectives.
    token_p50_min: int | None = Field(default=None, ge=0, le=4000, description="Target P50 chunk token length (min)")
    token_p50_max: int | None = Field(default=None, ge=0, le=4000, description="Target P50 chunk token length (max)")

    # Ratio checks (percentage points, 0-100).
    short_pct_warn: int | None = Field(
        default=None, ge=0, le=100, description="Warn threshold for short chunk ratio (<=100 tokens)"
    )
    short_pct_fail: int | None = Field(
        default=None, ge=0, le=100, description="Fail threshold for short chunk ratio (<=100 tokens)"
    )
    long_pct_warn: int | None = Field(
        default=None, ge=0, le=100, description="Warn threshold for long chunk ratio (>=800 tokens)"
    )
    long_pct_fail: int | None = Field(
        default=None, ge=0, le=100, description="Fail threshold for long chunk ratio (>=800 tokens)"
    )

    # Chunk overlap waste objectives (percentage points, 0-100).
    overlap_waste_p50_warn: int | None = Field(
        default=None, ge=0, le=100, description="Warn threshold for overlap waste P50 (%)"
    )
    overlap_waste_p50_fail: int | None = Field(
        default=None, ge=0, le=100, description="Fail threshold for overlap waste P50 (%)"
    )

    # Chunk coverage objectives (percentage points, 0-100). This is best-effort and may be missing.
    coverage_p50_warn: int | None = Field(default=None, ge=0, le=100, description="Warn threshold for coverage P50 (%)")
    coverage_p50_fail: int | None = Field(default=None, ge=0, le=100, description="Fail threshold for coverage P50 (%)")


class DatasetRAGDefaults(BaseModel):
    """
    Dataset-level default RAG settings (optional overrides).

    These defaults are applied when the chat request doesn't explicitly provide the corresponding fields.
    """

    model_config = ConfigDict(extra="ignore")

    # Optional retrieval preset (applied by ChatRAGConfig validator when merged).
    retrieval_profile: str | None = None
    # Optional deterministic intent router toggle + policy overlay.
    intent_router: bool | None = None
    intent_router_policy: dict[str, Any] | None = None

    # Controlled query expansion for recall (optional).
    enable_query_alias_expansion: bool | None = None
    query_aliases: dict[str, list[str]] | None = None
    query_alias_max_queries: int | None = Field(default=None, ge=0, le=20)

    # Optional: per-dataset overrides for LLM multi-query generation (inherits global settings when None).
    enable_multi_query: bool | None = None
    multi_query_count: int | None = Field(default=None, ge=1, le=8)
    multi_query_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    multi_query_max_chars: int | None = Field(default=None, ge=0, le=2000)
    enable_hyde: bool | None = None

    # Optional hierarchy-aware recall overlay.
    enable_hierarchy_recall: bool | None = None
    hierarchy_family_collapse: bool | None = None
    hierarchy_family_aggregation: Literal["frequency", "score", "combined"] | None = None
    hierarchy_tree_dedup: bool | None = None
    hierarchy_parent_depth: int | None = Field(default=None, ge=0, le=8)
    hierarchy_sibling_window: int | None = Field(default=None, ge=0, le=16)
    hierarchy_overfetch_factor: int | None = Field(default=None, ge=1, le=32)

    top_k: int | None = Field(default=None, ge=1, le=100)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    retrieval_mode: str | None = None  # hybrid | vector | keyword | mmr | auto
    retrieval_contract_mode: str | None = None
    alpha: float | None = Field(default=None, ge=0.0, le=1.0)

    # Retrieval channel fusion strategy override (optional, dataset-scoped).
    # Supported: linear | rrf | budgeted_rrf | weighted
    fusion_strategy: str | None = None
    # Only used by fusion_strategy=budgeted_rrf (ignored otherwise).
    fusion_budgets: dict[str, int] | None = None
    fusion_min_scores: dict[str, float] | None = None
    # Only used by fusion_strategy=weighted (ignored otherwise).
    fusion_weights: dict[str, float] | None = None

    enable_weight_rerank: bool | None = None
    vector_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    keyword_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    mmr_lambda: float | None = Field(default=None, ge=0.0, le=1.0)

    enable_reranker: bool | None = None
    reranker_provider: str | None = None

    reranker_top_n: int | None = Field(default=None, ge=1, le=200)

    # Optional strict grounding mode: treat missing evidence as non-existent and abstain early.
    # Also forces post-generation claim-check (may buffer streaming).
    visible_evidence_only: bool | None = None

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def _normalize_retrieval_mode(cls, value: Any) -> str | None:
        if value is None:
            return None
        mode = str(value)
        return normalize_retrieval_mode(mode) if mode.strip() else None

    @field_validator("retrieval_contract_mode", mode="before")
    @classmethod
    def _normalize_retrieval_contract_mode(cls, value: Any) -> str | None:
        if value is None:
            return None
        mode = normalize_retrieval_contract_mode(value)
        if mode not in VALID_RETRIEVAL_CONTRACT_MODES:
            raise ValueError(
                "retrieval_contract_mode must be one of: " + ", ".join(sorted(VALID_RETRIEVAL_CONTRACT_MODES))
            )
        return mode

    @field_validator("hierarchy_family_aggregation", mode="before")
    @classmethod
    def _normalize_hierarchy_family_aggregation(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(
                "hierarchy_family_aggregation must be one of: " + ", ".join(HIERARCHY_FAMILY_AGGREGATION_VALUES)
            )
        raw = value.strip().lower()
        if not raw:
            return None
        if raw not in HIERARCHY_FAMILY_AGGREGATION_VALUES:
            raise ValueError(
                "hierarchy_family_aggregation must be one of: " + ", ".join(HIERARCHY_FAMILY_AGGREGATION_VALUES)
            )
        return raw

    @model_validator(mode="after")
    def _validate_fusion_dicts(self) -> "DatasetRAGDefaults":
        """Check channel names; effective numeric limits belong to ChatRAGConfig after merging."""
        _validate_fusion_map_keys(self.fusion_budgets, field_name="fusion_budgets")
        _validate_fusion_map_keys(self.fusion_min_scores, field_name="fusion_min_scores")
        _validate_fusion_map_keys(self.fusion_weights, field_name="fusion_weights")
        return self


class DatasetEmbeddingDefaults(BaseModel):
    """
    Dataset-level embedding defaults.

    Stored in datasets.metadata.embedding_defaults. API keys intentionally stay
    in system settings; dataset metadata only chooses the embedding space.
    """

    model_config = ConfigDict(extra="ignore")

    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=200)
    api_base: str | None = Field(default=None, max_length=1000)

    @field_validator("provider", "model", "api_base", mode="after")
    @classmethod
    def _strip_empty_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value if value else None


class DatasetRetentionPolicy(BaseModel):
    """
    Dataset-level retention policy (Gap9).

    Stored in datasets.metadata.retention_policy.
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    action: Literal["archive", "delete"] = "archive"
    max_age_days: int | None = Field(default=None, ge=1, le=3650, description="Expire docs older than this many days")
    max_inactive_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="Expire docs with no recent activity (best-effort; uses updated_at fallback)",
    )
    max_versions: int | None = Field(default=None, ge=1, le=50, description="Keep at most N pipeline versions per doc")


class DatasetBase(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = None
    permission: DatasetPermissionEnum = DatasetPermissionEnum.ALL_TEAM_MEMBERS
    partial_member_list: list[str] | None = None
    partial_group_list: list[UUID] | None = Field(default=None, max_length=200)
    # Dataset-level ingestion defaults (applied when the request uses global defaults).
    default_parser_backend: str | None = None
    default_chunk_strategy: str | None = None
    # Dataset-level default RAG settings (applied when chat doesn't specify).
    rag_defaults: DatasetRAGDefaults | None = None
    # Dataset-level embedding defaults (applied to this dataset's embedding space).
    embedding_defaults: DatasetEmbeddingDefaults | None = None
    # Dataset-level default RAG config template selectors (optional; used for safe rollout/rollback).
    default_rag_config_template_id: UUID | None = None
    default_rag_config_template_key: str | None = None
    default_rag_config_ab_experiment_key: str | None = None
    # Dataset-level default prompt settings (applied when chat doesn't specify).
    default_prompt_template_id: UUID | None = None
    default_prompt_template_key: str | None = None
    default_prompt_ab_experiment_key: str | None = None
    # Dataset-level chunk targets (best-effort tuning objectives for profiling/auto-tune).
    chunk_targets_v2: DatasetChunkTargetsV2 | None = None
    # Dataset-level pipeline defaults (governance/indexing). If omitted, tenant defaults apply.
    pipeline: DocumentPipelineOptions | None = None
    retention_policy: DatasetRetentionPolicy | None = None


def validate_dataset_execution(
    embedding: DatasetEmbeddingDefaults | None,
    rag: DatasetRAGDefaults | None,
    pipeline: DocumentPipelineOptions | None,
    parser_backend: str | None = None,
) -> None:
    reject_retired_provider(parser_backend, capability="parser")

    if embedding is not None:
        reject_retired_provider(embedding.provider, capability="embedding")
    if rag is not None:
        validate_rag_execution_selection(
            reranker_provider=rag.reranker_provider, retrieval_profile=rag.retrieval_profile
        )
    if pipeline is not None:
        reject_retired_provider(pipeline.governance_keywords_provider, capability="keyword")


class DatasetCreate(DatasetBase):
    @model_validator(mode="after")
    def _validate_execution(self) -> "DatasetCreate":
        validate_dataset_execution(
            self.embedding_defaults, self.rag_defaults, self.pipeline, self.default_parser_backend
        )
        return self


class DatasetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permission: DatasetPermissionEnum | None = None
    partial_member_list: list[str] | None = None
    partial_group_list: list[UUID] | None = Field(default=None, max_length=200)
    default_parser_backend: str | None = None
    default_chunk_strategy: str | None = None
    rag_defaults: DatasetRAGDefaults | None = None
    embedding_defaults: DatasetEmbeddingDefaults | None = None
    default_rag_config_template_id: UUID | None = None
    default_rag_config_template_key: str | None = None
    default_rag_config_ab_experiment_key: str | None = None
    default_prompt_template_id: UUID | None = None
    default_prompt_template_key: str | None = None
    default_prompt_ab_experiment_key: str | None = None
    chunk_targets_v2: DatasetChunkTargetsV2 | None = None
    pipeline: DocumentPipelineOptions | None = None
    retention_policy: DatasetRetentionPolicy | None = None

    @model_validator(mode="after")
    def _validate_execution(self) -> "DatasetUpdate":
        validate_dataset_execution(
            self.embedding_defaults, self.rag_defaults, self.pipeline, self.default_parser_backend
        )
        return self


DatasetOperationalStatus = Literal["active", "anomaly", "pending", "testing"]


class DatasetListIngestionSummary(BaseModel):
    total_documents: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    total_chunks: int = 0
    total_size: int = 0
    total_characters: int = 0
    last_processed_at: datetime | None = None


class DatasetListFacets(BaseModel):
    scope_total: int = 0
    filtered_total: int = 0
    status_counts: dict[DatasetOperationalStatus, int] = Field(default_factory=dict)


class DatasetOut(OrmModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    permission: DatasetPermissionEnum
    owner_id: str | None
    partial_member_list: list[str] | None = None
    partial_group_list: list[UUID] | None = None
    default_parser_backend: str | None = None
    default_chunk_strategy: str | None = None
    rag_defaults: DatasetRAGDefaults | None = None
    embedding_defaults: DatasetEmbeddingDefaults | None = None
    default_rag_config_template_id: UUID | None = None
    default_rag_config_template_key: str | None = None
    default_rag_config_ab_experiment_key: str | None = None
    default_prompt_template_id: UUID | None = None
    default_prompt_template_key: str | None = None
    default_prompt_ab_experiment_key: str | None = None
    chunk_targets_v2: DatasetChunkTargetsV2 | None = None
    pipeline: DocumentPipelineOptions | None = None
    retention_policy: DatasetRetentionPolicy | None = None
    ingestion_summary: DatasetListIngestionSummary | None = None
    operational_status: DatasetOperationalStatus | None = None


class DatasetListResponse(BaseModel):
    total: int
    items: list[DatasetOut]
    facets: DatasetListFacets | None = None


class DatasetIngestionStats(DatasetListIngestionSummary):
    """Lightweight dataset ingestion stats for dashboards."""

    dataset_id: UUID


class DatasetConfigBundle(BaseModel):
    """
    Dataset-level configuration bundle (portable).

    Used for export/import/clone to standardize ingestion + retrieval behavior
    across datasets without introducing visual workflow editors.
    """

    default_parser_backend: str | None = None
    default_chunk_strategy: str | None = None
    rag_defaults: DatasetRAGDefaults | None = None
    embedding_defaults: DatasetEmbeddingDefaults | None = None
    default_rag_config_template_id: UUID | None = None
    default_rag_config_template_key: str | None = None
    default_rag_config_ab_experiment_key: str | None = None
    default_prompt_template_id: UUID | None = None
    default_prompt_template_key: str | None = None
    default_prompt_ab_experiment_key: str | None = None
    chunk_targets_v2: DatasetChunkTargetsV2 | None = None
    pipeline: DocumentPipelineOptions | None = None
    retention_policy: DatasetRetentionPolicy | None = None
    ingestion_policy: IngestionPolicy | None = None
    fls_policy: FlsPolicy | None = None
    workflow_layout: dict[str, Any] | None = None


class DatasetConfigExport(BaseModel):
    version: str = "1"
    dataset_id: UUID
    name: str
    exported_at: datetime
    config: DatasetConfigBundle


class DatasetConfigImportRequest(BaseModel):
    config: DatasetConfigBundle
    replace: bool = False


class DatasetPurgeResponse(BaseModel):
    dataset_id: UUID
    dry_run: bool = True
    max_delete: int
    eligible: int
    deleted: int
    not_found: int = 0
    denied: int = 0
    conflicts: int = 0
    errors: int = 0


class DatasetCloneRequest(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = None
    copy_permission: bool = True
    copy_partial_members: bool = True
