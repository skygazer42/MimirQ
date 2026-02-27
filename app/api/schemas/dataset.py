"""
Dataset-related Pydantic schemas.
Defines data models for dataset creation, update, and query endpoints.
"""
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.dataset import DatasetPermissionEnum
from app.rag.core.text import normalize_retrieval_mode

from .base import OrmModel
from .document import DocumentPipelineOptions
from .fls_policy import FlsPolicy
from .ingestion_policy import IngestionPolicy


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

    # Token distribution objectives.
    token_p50_min: Optional[int] = Field(default=None, ge=0, le=4000, description="Target P50 chunk token length (min)")
    token_p50_max: Optional[int] = Field(default=None, ge=0, le=4000, description="Target P50 chunk token length (max)")

    # Ratio checks (percentage points, 0-100).
    short_pct_warn: Optional[int] = Field(default=None, ge=0, le=100, description="Warn threshold for short chunk ratio (<=100 tokens)")
    short_pct_fail: Optional[int] = Field(default=None, ge=0, le=100, description="Fail threshold for short chunk ratio (<=100 tokens)")
    long_pct_warn: Optional[int] = Field(default=None, ge=0, le=100, description="Warn threshold for long chunk ratio (>=800 tokens)")
    long_pct_fail: Optional[int] = Field(default=None, ge=0, le=100, description="Fail threshold for long chunk ratio (>=800 tokens)")

    # Chunk overlap waste objectives (percentage points, 0-100).
    overlap_waste_p50_warn: Optional[int] = Field(default=None, ge=0, le=100, description="Warn threshold for overlap waste P50 (%)")
    overlap_waste_p50_fail: Optional[int] = Field(default=None, ge=0, le=100, description="Fail threshold for overlap waste P50 (%)")

    # Chunk coverage objectives (percentage points, 0-100). This is best-effort and may be missing.
    coverage_p50_warn: Optional[int] = Field(default=None, ge=0, le=100, description="Warn threshold for coverage P50 (%)")
    coverage_p50_fail: Optional[int] = Field(default=None, ge=0, le=100, description="Fail threshold for coverage P50 (%)")

    model_config = ConfigDict(extra="ignore")


class DatasetRAGDefaults(BaseModel):
    """
    Dataset-level default RAG settings (optional overrides).

    These defaults are applied when the chat request doesn't explicitly provide the corresponding fields.
    """

    # Optional retrieval preset (applied by ChatRAGConfig validator when merged).
    retrieval_profile: Optional[str] = None

    # Controlled query expansion for recall (optional).
    enable_query_alias_expansion: Optional[bool] = None
    query_aliases: Optional[Dict[str, List[str]]] = None
    query_alias_max_queries: Optional[int] = Field(default=None, ge=0, le=20)

    # Optional: per-dataset overrides for LLM multi-query generation (inherits global settings when None).
    enable_multi_query: Optional[bool] = None
    multi_query_count: Optional[int] = Field(default=None, ge=1, le=8)
    multi_query_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    multi_query_max_chars: Optional[int] = Field(default=None, ge=0, le=2000)

    top_k: Optional[int] = Field(default=None, ge=1, le=100)
    score_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    retrieval_mode: Optional[str] = None  # hybrid | vector | keyword | mmr | auto
    alpha: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    enable_weight_rerank: Optional[bool] = None
    vector_weight: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    keyword_weight: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    mmr_lambda: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    enable_reranker: Optional[bool] = None
    reranker_provider: Optional[str] = None
    reranker_top_n: Optional[int] = Field(default=None, ge=1, le=200)

    # Optional strict grounding mode: treat missing evidence as non-existent and abstain early.
    # Also forces post-generation claim-check (may buffer streaming).
    visible_evidence_only: Optional[bool] = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def _normalize_retrieval_mode(cls, v):  # noqa: ANN001
        if v is None:
            return None
        s = str(v)
        return normalize_retrieval_mode(s) if s.strip() else None


class DatasetBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    permission: DatasetPermissionEnum = DatasetPermissionEnum.ALL_TEAM_MEMBERS
    partial_member_list: Optional[List[str]] = None
    # Dataset-level ingestion defaults (applied when the request uses global defaults).
    default_parser_backend: Optional[str] = None
    default_chunk_strategy: Optional[str] = None
    # Dataset-level default RAG settings (applied when chat doesn't specify).
    rag_defaults: Optional[DatasetRAGDefaults] = None
    # Dataset-level default prompt settings (applied when chat doesn't specify).
    default_prompt_template_id: Optional[UUID] = None
    default_prompt_template_key: Optional[str] = None
    default_prompt_ab_experiment_key: Optional[str] = None
    # Dataset-level chunk targets (best-effort tuning objectives for profiling/auto-tune).
    chunk_targets_v2: Optional[DatasetChunkTargetsV2] = None
    # Dataset-level pipeline defaults (governance/indexing). If omitted, tenant defaults apply.
    pipeline: Optional[DocumentPipelineOptions] = None


class DatasetCreate(DatasetBase):
    pass


class DatasetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission: Optional[DatasetPermissionEnum] = None
    partial_member_list: Optional[List[str]] = None
    default_parser_backend: Optional[str] = None
    default_chunk_strategy: Optional[str] = None
    rag_defaults: Optional[DatasetRAGDefaults] = None
    default_prompt_template_id: Optional[UUID] = None
    default_prompt_template_key: Optional[str] = None
    default_prompt_ab_experiment_key: Optional[str] = None
    chunk_targets_v2: Optional[DatasetChunkTargetsV2] = None
    pipeline: Optional[DocumentPipelineOptions] = None


class DatasetOut(OrmModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str]
    permission: DatasetPermissionEnum
    owner_id: Optional[str]
    partial_member_list: Optional[List[str]] = None
    default_parser_backend: Optional[str] = None
    default_chunk_strategy: Optional[str] = None
    rag_defaults: Optional[DatasetRAGDefaults] = None
    default_prompt_template_id: Optional[UUID] = None
    default_prompt_template_key: Optional[str] = None
    default_prompt_ab_experiment_key: Optional[str] = None
    chunk_targets_v2: Optional[DatasetChunkTargetsV2] = None
    pipeline: Optional[DocumentPipelineOptions] = None


class DatasetListResponse(BaseModel):
    total: int
    items: List[DatasetOut]


class DatasetIngestionStats(BaseModel):
    """Lightweight dataset ingestion stats for dashboards."""

    dataset_id: UUID
    total_documents: int
    by_status: Dict[str, int] = Field(default_factory=dict)
    total_chunks: int = 0
    total_size: int = 0
    total_characters: int = 0
    last_processed_at: Optional[datetime] = None


class DatasetConfigBundle(BaseModel):
    """
    Dataset-level configuration bundle (portable).

    Used for export/import/clone to standardize ingestion + retrieval behavior
    across datasets without introducing visual workflow editors.
    """

    default_parser_backend: Optional[str] = None
    default_chunk_strategy: Optional[str] = None
    rag_defaults: Optional[DatasetRAGDefaults] = None
    default_prompt_template_id: Optional[UUID] = None
    default_prompt_template_key: Optional[str] = None
    default_prompt_ab_experiment_key: Optional[str] = None
    chunk_targets_v2: Optional[DatasetChunkTargetsV2] = None
    pipeline: Optional[DocumentPipelineOptions] = None
    ingestion_policy: Optional[IngestionPolicy] = None
    fls_policy: Optional[FlsPolicy] = None


class DatasetConfigExport(BaseModel):
    version: str = Field(default="1")
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
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    copy_permission: bool = True
    copy_partial_members: bool = True
