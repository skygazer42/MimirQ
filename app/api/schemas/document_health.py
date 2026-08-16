"""
Document health card schemas (Gap10).

This is a thin, PII-safe aggregation layer over existing parsing/chunking/KG/retrieval signals.
"""


from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentHealthParsing(BaseModel):
    parser_backend: str | None = None
    parser_backend_requested: str | None = None
    parse_quality: dict[str, Any] | None = None
    pdf_quality: dict[str, Any] | None = None
    seal_summary: dict[str, Any] | None = None

    is_scanned: bool | None = None
    page_count: int | None = None

    processed_at: datetime | None = None


class DocumentHealthChunkCoverage(BaseModel):
    sum_chunk_chars: int = 0
    covered_chars: int = 0
    coverage_ratio: float = 0.0
    overlap_waste_ratio: float = 0.0
    gap_count: int = 0
    largest_gap: int = 0


class DocumentHealthSemanticQualitySummary(BaseModel):
    sampled_chunks: int = 0
    needs_review: int = 0
    needs_review_ratio: float = 0.0

    mean_information_density: float | None = None
    mean_semantic_completeness: float | None = None
    mean_self_containedness: float | None = None
    mean_pronoun_ratio: float | None = None

    overall_histogram_10: list[int] = Field(default_factory=list)
    note: str | None = None


class DocumentHealthChunking(BaseModel):
    chunk_strategy: str | None = None
    chunk_strategy_requested: str | None = None

    chunk_count: int = 0
    total_characters: int = 0

    coverage: DocumentHealthChunkCoverage = Field(default_factory=DocumentHealthChunkCoverage)
    semantic_quality: DocumentHealthSemanticQualitySummary | None = None


class DocumentHealthRetrievalHits(BaseModel):
    enabled: bool = False
    available: bool = False
    path: str | None = None

    window_minutes: int = 60
    max_bytes: int = 0
    truncated: bool = False

    traces_scanned: int = 0
    traces_with_hits: int = 0
    citations_matched: int = 0
    unique_chunks_matched: int | None = None
    hit_rate: float | None = None


class DocumentHealthIndexChannelStatus(BaseModel):
    channel: str
    required: bool = False
    enabled: bool = False
    status: str = "pending"
    error: str | None = None
    attempt_count: int = 0
    last_attempted_at: datetime | None = None
    last_succeeded_at: datetime | None = None
    last_failed_at: datetime | None = None
    last_status_changed_at: datetime | None = None
    legacy: bool = False


class DocumentHealthIndexReadiness(BaseModel):
    pipeline_hash: str | None = None
    ready: bool = False
    pending_channels: list[str] = Field(default_factory=list)
    error_channels: list[str] = Field(default_factory=list)
    disabled_channels: list[str] = Field(default_factory=list)
    required_channels: list[str] = Field(default_factory=list)
    enabled_channels: list[str] = Field(default_factory=list)
    statuses: dict[str, DocumentHealthIndexChannelStatus] = Field(default_factory=dict)


class DocumentHealthCard(BaseModel):
    document_id: UUID
    dataset_id: UUID | None = None
    filename: str | None = None
    file_type: str | None = None
    file_size: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    generated_at: datetime
    status: str | None = None

    parsing: DocumentHealthParsing
    chunking: DocumentHealthChunking
    kg: dict[str, Any] | None = None
    retrieval_hits: DocumentHealthRetrievalHits | None = None
    index_readiness: DocumentHealthIndexReadiness | None = None
