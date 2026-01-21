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
    governance_extract_frontmatter: Optional[bool] = Field(default=None, description="Extract Markdown YAML frontmatter for metadata enrichment")
    governance_strip_frontmatter: Optional[bool] = Field(default=None, description="Strip Markdown YAML frontmatter from content after extraction")
    governance_detect_language: Optional[bool] = Field(default=None, description="Detect primary language/script (zh/en/mixed) for metadata enrichment")
    governance_language_min_chars: Optional[int] = Field(default=None, ge=0, le=200_000, description="Min alnum/CJK chars before language detection triggers")
    governance_normalize_urls: Optional[bool] = Field(default=None, description="Normalize URLs (e.g., strip tracking parameters) for consistency/dedup")
    governance_normalize_urls_strip_tracking: Optional[bool] = Field(default=None, description="When normalizing URLs, strip common tracking parameters (utm_*, gclid, fbclid, etc.)")
    governance_drop_duplicate_paragraphs: Optional[bool] = Field(default=None, description="Drop paragraphs repeated many times within a document (best-effort)")
    governance_drop_duplicate_paragraphs_min_occurrences: Optional[int] = Field(default=None, ge=2, le=100, description="Min repeat occurrences to drop a paragraph")
    governance_drop_duplicate_paragraphs_min_chars: Optional[int] = Field(default=None, ge=0, le=50_000, description="Min paragraph chars to consider for dedup")
    governance_drop_duplicate_paragraphs_max_chars: Optional[int] = Field(default=None, ge=0, le=200_000, description="Max paragraph chars to consider for dedup (0 disables cap)")
    governance_trim_references: Optional[bool] = Field(default=None, description="Trim trailing reference/bibliography sections (best-effort)")
    governance_extract_keywords: Optional[bool] = Field(default=None, description="Extract document-level keywords for metadata enrichment (best-effort)")
    governance_keywords_provider: Optional[str] = Field(default=None, description="Keyword provider: auto / jieba / jieba_textrank / hanlp / simple")
    governance_keywords_top_k: Optional[int] = Field(default=None, ge=1, le=100, description="Max keywords to extract")
    governance_keywords_max_chars: Optional[int] = Field(default=None, ge=0, le=2_000_000, description="Max chars used for keyword extraction (truncate when exceeded)")
    governance_normalize_tables: Optional[bool] = Field(default=None, description="Normalize markdown tables (whitespace/column alignment)")
    governance_strip_code_line_numbers: Optional[bool] = Field(default=None, description="Strip leading line numbers inside fenced code blocks")
    governance_pii_anonymize: Optional[bool] = None
    governance_pii_mode: Optional[str] = Field(
        default=None,
        description="PII anonymization mode: mask | token",
    )
    governance_pii_mask: Optional[str] = Field(default=None, description="PII replacement string (mask mode)")
    governance_secrets_redact: Optional[bool] = Field(default=None, description="Redact common secrets/tokens (API keys, private keys, bearer tokens)")
    governance_secrets_mode: Optional[str] = Field(default=None, description="Secrets redaction mode: mask | token")
    governance_secrets_mask: Optional[str] = Field(default=None, description="Secrets replacement string (mask mode)")
    governance_max_blank_lines: Optional[int] = Field(default=None, ge=0, le=10, description="Max consecutive blank lines")
    governance_html_xpath: Optional[str] = Field(default=None, description="XPath for HTML extraction (HTML/HTM)")
    governance_drop_outline_only: Optional[bool] = None
    governance_drop_outline_min_content_chars: Optional[int] = Field(default=None, ge=0, le=200_000, description="Min content chars before outline filter triggers")
    governance_drop_outline_max_heading_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Heading-like paragraph ratio threshold")
    governance_drop_low_density: Optional[bool] = None
    governance_drop_low_density_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Alnum/CJK density threshold")
    governance_quarantine_on_drop: Optional[bool] = Field(
        default=None,
        description="When governance drop filters trigger, mark document as quarantined instead of failed",
    )
    governance_unwrap_max_line_length: Optional[int] = Field(default=None, ge=40, le=400, description="max line length")
    governance_noise_min_chars: Optional[int] = Field(default=None, ge=1, le=20, description="noise min chars")
    governance_noise_ratio_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="noise ratio threshold")
    governance_common_lines_min_docs: Optional[int] = Field(default=None, ge=2, le=50, description="common line min docs")
    governance_common_lines_min_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="common line ratio")
    parse_fallback_enabled: Optional[bool] = Field(default=None, description="Retry parsing with an alternative backend when output quality is low (PDF only)")
    parse_fallback_min_content_chars: Optional[int] = Field(default=None, ge=0, le=200_000, description="Min alnum/CJK chars to consider parse successful")
    parse_fallback_max_retries: Optional[int] = Field(default=None, ge=0, le=3, description="Max parse fallback retries")
    persist_parsed_content: Optional[bool] = Field(default=None, description="Persist parsed markdown (raw+clean) into document_parsed_contents")
    persist_parsed_content_max_chars: Optional[int] = Field(default=None, ge=0, le=2_000_000, description="Max chars to persist (truncate when exceeded)")
    near_dedup_enabled: Optional[bool] = Field(default=None, description="Enable cross-document near-duplicate chunk dropping (SimHash)")
    near_dedup_hamming_threshold: Optional[int] = Field(default=None, ge=0, le=64, description="Near-dup Hamming distance threshold")
    near_dedup_max_bucket_size: Optional[int] = Field(default=None, ge=8, le=100_000, description="Max bucket size for near-dup index")
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
