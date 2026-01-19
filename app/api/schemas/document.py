"""
Document-related Pydantic schemas.
"""
from pydantic import AliasChoices, BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

from .base import OrmModel


class DocumentPipelineOptions(BaseModel):
    """Per-document pipeline options."""
    governance_enabled: Optional[bool] = None
    governance_remove_toc_lines: Optional[bool] = None
    governance_remove_noise_lines: Optional[bool] = None
    governance_unwrap_lines: Optional[bool] = None
    governance_remove_common_lines: Optional[bool] = None
    governance_remove_boilerplate: Optional[bool] = None
    governance_remove_images: Optional[str] = Field(
        default=None,
        description="Image removal mode: none | decorative | all",
    )
    governance_pii_anonymize: Optional[bool] = None
    governance_pii_mode: Optional[str] = Field(
        default=None,
        description="PII anonymization mode: mask | token",
    )
    governance_pii_mask: Optional[str] = Field(default=None, description="PII replacement string (mask mode)")
    governance_max_blank_lines: Optional[int] = Field(default=None, ge=0, le=10, description="Max consecutive blank lines")
    governance_html_xpath: Optional[str] = Field(default=None, description="XPath for HTML extraction (HTML/HTM)")
    governance_drop_outline_only: Optional[bool] = None
    governance_drop_outline_min_content_chars: Optional[int] = Field(default=None, ge=0, le=200_000, description="Min content chars before outline filter triggers")
    governance_drop_outline_max_heading_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Heading-like paragraph ratio threshold")
    governance_drop_low_density: Optional[bool] = None
    governance_drop_low_density_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Alnum/CJK density threshold")
    governance_unwrap_max_line_length: Optional[int] = Field(default=None, ge=40, le=400, description="max line length")
    governance_noise_min_chars: Optional[int] = Field(default=None, ge=1, le=20, description="noise min chars")
    governance_noise_ratio_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="noise ratio threshold")
    governance_common_lines_min_docs: Optional[int] = Field(default=None, ge=2, le=50, description="common line min docs")
    governance_common_lines_min_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="common line ratio")
    chunk_size: Optional[int] = Field(default=None, ge=100, le=4000, description="Chunk size")
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=1000, description="Overlap size")
    chunk_vector_enabled: Optional[bool] = None
    bm25_index_enabled: Optional[bool] = None
    kg_enabled: Optional[bool] = None
    event_vector_enabled: Optional[bool] = None
    entity_vector_enabled: Optional[bool] = None


class DocumentUserMetadataPatchRequest(BaseModel):
    """
    Patch `documents.metadata.user` (user-editable metadata namespace).

    - When `replace=false` (default), merge keys into existing `metadata.user`.
    - When `replace=true`, replace the whole `metadata.user` object.
    - Any key with value `null` will be removed (merge mode only).
    """

    patch: Dict[str, Any] = Field(default_factory=dict, description="User metadata patch; null values remove keys.")
    replace: bool = Field(default=False, description="Replace entire metadata.user instead of merging")


class DocumentBatchUserMetadataPatchRequest(BaseModel):
    """Batch patch for `documents.metadata.user`."""

    document_ids: List[UUID] = Field(..., min_length=1, max_length=200)
    patch: Dict[str, Any] = Field(default_factory=dict)
    replace: bool = False


class DocumentBatchUserMetadataPatchResponse(BaseModel):
    """Batch patch result."""

    updated: int
    not_found: List[UUID] = Field(default_factory=list)
    denied: List[UUID] = Field(default_factory=list)


class DocumentChunkSchema(OrmModel):
    """Document chunk."""
    id: UUID
    content: str
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    chunk_index: int
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("doc_metadata", "metadata"),
    )


class GovernanceInfo(BaseModel):
    enabled: bool = False
    documents: int = 0
    changed_documents: int = 0
    rules_applied: int = 0
    dropped_documents: int = 0
    drop_reasons: Dict[str, int] = Field(default_factory=dict)


class DocumentDetail(OrmModel):
    """Document detail."""
    id: UUID
    filename: str
    file_type: str
    file_size: int
    status: str
    processing_progress: int
    chunk_count: int
    total_characters: int
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    dataset_id: Optional[UUID] = None
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("doc_metadata", "metadata"),
    )
    governance: GovernanceInfo = Field(default_factory=GovernanceInfo)
    # Avoid accidental lazy-loading on list endpoints: only include chunks when
    # the API handler explicitly sets `chunks_loaded` on the ORM instance.
    chunks: Optional[List[DocumentChunkSchema]] = Field(default=None, validation_alias="chunks_loaded")

    @model_validator(mode="after")
    def _populate_governance(self) -> "DocumentDetail":
        meta = self.metadata or {}
        try:
            self.governance = GovernanceInfo(
                enabled=bool(meta.get("governance_enabled") or False),
                documents=int(meta.get("governance_documents") or 0),
                changed_documents=int(meta.get("governance_changed_documents") or 0),
                rules_applied=int(meta.get("governance_rules_applied") or 0),
                dropped_documents=int(meta.get("governance_dropped_documents") or 0),
                drop_reasons=meta.get("governance_drop_reasons") if isinstance(meta.get("governance_drop_reasons"), dict) else {},
            )
        except (TypeError, ValueError):
            self.governance = GovernanceInfo()
        return self


class ParsedSegment(BaseModel):
    """Document parse preview segment."""
    index: int
    content: str
    page_number: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentParsePreview(BaseModel):
    """Document parse preview result."""
    filename: str
    file_type: str
    file_size: int
    segments: List[ParsedSegment]
    parser_backend: str


class ManualChunkCreate(BaseModel):
    """Single chunk entry in a manual chunking request."""
    content: str
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ManualDocumentCreate(BaseModel):
    """Request to create a document from manual chunks."""
    dataset_id: Optional[UUID] = None
    filename: str
    file_type: str
    file_size: int
    chunks: List[ManualChunkCreate]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    pipeline: Optional[DocumentPipelineOptions] = None


class DocumentList(BaseModel):
    """Document list."""
    total: int
    items: List[DocumentDetail]


class DocumentStatus(OrmModel):
    """Document processing status."""
    id: UUID
    status: str
    processing_progress: int
    current_stage: Optional[str] = None
    error_message: Optional[str] = None


# ============ Chunk preview schemas ============

class ChunkPreviewParams(BaseModel):
    """Chunk preview parameters."""
    chunk_size: int = Field(default=1000, ge=100, le=4000, description="Chunk size")
    chunk_overlap: int = Field(default=200, ge=0, le=1000, description="Overlap size")
    unit: str = Field(default="chars", description="chunk_size/chunk_overlap unit: chars | tokens")


class ChunkPreviewItem(BaseModel):
    """Chunk preview item."""
    index: int
    content: str
    length: int
    start_index: int  # Start position in original text.
    end_index: int    # End position in original text.
    page_number: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChunkPreviewResponse(BaseModel):
    """Chunk preview response."""
    filename: str
    file_type: str
    file_size: int
    total_chunks: int
    total_characters: int
    params: ChunkPreviewParams
    chunks: List[ChunkPreviewItem]
    # Original text for frontend highlighting.
    original_text: Optional[str] = None
    parser_backend: str
    chunk_strategy: str


# ============ Batch upload schemas ============

class BatchFileInfo(BaseModel):
    """Batch upload file info."""
    name: str = Field(..., description="Filename")
    data_id: str = Field(..., description="Custom data ID for file identification")


class BatchUploadRequest(BaseModel):
    """Batch request for upload URLs."""
    files: List[BatchFileInfo] = Field(..., max_length=200, description="File list, max 200 files")


class BatchUploadResponse(BaseModel):
    """Batch response for upload URLs."""
    batch_id: str = Field(..., description="Batch ID")
    file_urls: List[str] = Field(..., description="Upload URL list")
    files: List[BatchFileInfo] = Field(..., description="File info list")
    message: str = Field(default="Upload URLs generated. Please upload files within 24 hours.")


class BatchTaskStatus(BaseModel):
    """Batch task status."""
    batch_id: str
    status: str = Field(..., description="Task status: pending, processing, completed, failed")
    total_files: int
    completed_files: int
    failed_files: int
    progress: int = Field(..., ge=0, le=100, description="Progress percentage")
    result_url: Optional[str] = None
    error: Optional[str] = None


# ============ Batch file upload (multiple files per request) schemas ============

class DocumentBatchUploadSuccess(BaseModel):
    """Single file result for successful batch upload (lightweight response)."""
    document_id: UUID
    filename: str
    status: str


class DocumentBatchUploadFailure(BaseModel):
    """Single file result for failed batch upload."""
    filename: str
    error: str


class DocumentBatchUploadResponse(BaseModel):
    """Batch upload endpoint response."""
    total: int
    successful_count: int
    failed_count: int
    successful: List[DocumentBatchUploadSuccess] = Field(default_factory=list)
    failed: List[DocumentBatchUploadFailure] = Field(default_factory=list)
