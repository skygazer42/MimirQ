"""Request contracts shared by document ingestion routes."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Form
from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.document import DocumentPipelineOptions
from app.core.config import settings


@dataclass(frozen=True)
class PipelineOptionOverrides:
    governance_enabled: bool | None = None
    governance_remove_toc_lines: bool | None = None
    governance_remove_noise_lines: bool | None = None
    governance_unwrap_lines: bool | None = None
    governance_remove_common_lines: bool | None = None
    governance_unwrap_max_line_length: int | None = None
    governance_noise_min_chars: int | None = None
    governance_noise_ratio_threshold: float | None = None
    governance_common_lines_min_docs: int | None = None
    governance_common_lines_min_ratio: float | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    chunk_vector_enabled: bool | None = None
    bm25_index_enabled: bool | None = None
    kg_enabled: bool | None = None
    event_vector_enabled: bool | None = None
    entity_vector_enabled: bool | None = None


class UrlUploadRequest(BaseModel):
    """Upload a document by fetching a remote URL (connector skeleton)."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., max_length=2000)
    dataset_id: UUID | None = None
    filename: str | None = Field(
        default=None, max_length=500, description="Optional override filename (used for extension + display)"
    )
    # Optional: authenticated fetch (cookie/bearer/basic) for private pages.
    fetch_headers: dict[str, str] | None = None
    user_agent: str | None = Field(default=None, max_length=200)
    parser_backend: str = Field(default=settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Field(default=settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: DocumentPipelineOptions | None = None


@dataclass
class PipelineOverridesFormFields:
    governance_enabled: bool | None = Form(None)
    governance_remove_toc_lines: bool | None = Form(None)
    governance_remove_noise_lines: bool | None = Form(None)
    governance_unwrap_lines: bool | None = Form(None)
    governance_remove_common_lines: bool | None = Form(None)
    governance_unwrap_max_line_length: int | None = Form(None)
    governance_noise_min_chars: int | None = Form(None)
    governance_noise_ratio_threshold: float | None = Form(None)
    governance_common_lines_min_docs: int | None = Form(None)
    governance_common_lines_min_ratio: float | None = Form(None)
    chunk_size: int | None = Form(None)
    chunk_overlap: int | None = Form(None)
    chunk_vector_enabled: bool | None = Form(None)
    bm25_index_enabled: bool | None = Form(None)
    kg_enabled: bool | None = Form(None)
    event_vector_enabled: bool | None = Form(None)
    entity_vector_enabled: bool | None = Form(None)


@dataclass
class UploadDocumentFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: str | None = Form(None)
    dataset_id: UUID | None = Form(None)
    user_metadata: str | None = Form(None)


@dataclass
class UploadDocumentsBatchFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: str | None = Form(None)
    dataset_id: UUID | None = Form(None)
    precheck_first: bool = Form(False)
    precheck_only: bool = Form(False)
    upload_only: bool = Form(False)
    user_metadata_map: str | None = Form(None)
    max_concurrent: int = Form(5)


class LocalHtmlIngestRequest(BaseModel):
    """Ingest a local HTML payload as a document (internal connector helper)."""

    model_config = ConfigDict(extra="forbid")

    html: str = Field(..., description="HTML content (fragment or full document)")
    source_url: str | None = Field(
        default=None, max_length=2000, description="Best-effort source URL for citations/debug"
    )
    dataset_id: UUID | None = None
    filename: str | None = Field(
        default=None, max_length=500, description="Optional override filename (used for extension + display)"
    )
    parser_backend: str = Field(default=settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Field(default=settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: DocumentPipelineOptions | None = None
