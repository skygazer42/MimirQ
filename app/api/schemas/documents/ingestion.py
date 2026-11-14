"""Pydantic request models shared by document ingestion routes."""

from uuid import UUID

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.documents.models import DocumentPipelineOptions
from app.core.config import settings


class UrlUploadRequest(BaseModel):
    """Upload a document by fetching a remote URL (connector skeleton)."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2000)
    dataset_id: UUID | None = None
    filename: str | None = Field(
        default=None, max_length=500, description="Optional override filename (used for extension + display)"
    )
    # Optional: authenticated fetch (cookie/bearer/basic) for private pages.
    fetch_headers: dict[str, str] | None = None
    user_agent: str | None = Field(default=None, max_length=200)
    parser_backend: str = settings.DEFAULT_PARSER_BACKEND
    chunk_strategy: str = settings.DEFAULT_CHUNK_STRATEGY
    pipeline: DocumentPipelineOptions | None = None


class LocalHtmlIngestRequest(BaseModel):
    """Ingest a local HTML payload as a document (internal connector helper)."""

    model_config = ConfigDict(extra="forbid")

    html: str = Field(description="HTML content (fragment or full document)")
    source_url: str | None = Field(
        default=None, max_length=2000, description="Best-effort source URL for citations/debug"
    )
    dataset_id: UUID | None = None
    filename: str | None = Field(
        default=None, max_length=500, description="Optional override filename (used for extension + display)"
    )
    parser_backend: str = settings.DEFAULT_PARSER_BACKEND
    chunk_strategy: str = settings.DEFAULT_CHUNK_STRATEGY
    pipeline: DocumentPipelineOptions | None = None


class PipelineOptionOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

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

    def to_pipeline_overrides(self) -> "PipelineOptionOverrides":
        values = self.model_dump(include=set(PipelineOptionOverrides.model_fields), exclude_none=True)
        return PipelineOptionOverrides.model_validate(values)


class DocumentPreviewForm(BaseModel):
    """One flat multipart body for parsing a document without persisting it."""

    model_config = ConfigDict(extra="ignore")

    parser_backend: str = settings.DEFAULT_PARSER_BACKEND
    chunk_strategy: str = settings.DEFAULT_CHUNK_STRATEGY
    dataset_id: str | None = None
    pipeline: str | None = None
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
    file: UploadFile

    @model_validator(mode="before")
    @classmethod
    def omit_empty_form_values(cls, data: object) -> object:
        # Individual FastAPI Form fields use their default for an exact empty string.
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value != ""}
        return data

    def to_pipeline_overrides(self) -> PipelineOptionOverrides:
        values = self.model_dump(include=set(PipelineOptionOverrides.model_fields))
        return PipelineOptionOverrides.model_validate(values)


class UploadDocumentFormFields(PipelineOptionOverrides):
    """One flat multipart body, including the upload and pipeline overrides."""

    model_config = ConfigDict(extra="ignore")

    parser_backend: str = settings.DEFAULT_PARSER_BACKEND
    chunk_strategy: str = settings.DEFAULT_CHUNK_STRATEGY
    pipeline: str | None = None
    dataset_id: UUID | None = None
    user_metadata: str | None = None
    file: UploadFile


class UploadDocumentsBatchFormFields(PipelineOptionOverrides):
    """One flat multipart body for a batch and its pipeline overrides."""

    model_config = ConfigDict(extra="ignore")

    parser_backend: str = settings.DEFAULT_PARSER_BACKEND
    chunk_strategy: str = settings.DEFAULT_CHUNK_STRATEGY
    pipeline: str | None = None
    dataset_id: UUID | None = None
    precheck_first: bool = False
    precheck_only: bool = False
    upload_only: bool = False
    user_metadata_map: str | None = None
    max_concurrent: int = 5
    files: list[UploadFile]
