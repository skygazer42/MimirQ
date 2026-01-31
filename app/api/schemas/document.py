"""
Document-related Pydantic schemas.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, model_validator

from .base import OrmModel


class GovernanceRegexRule(BaseModel):
    """Declarative regex cleanup rule (no executable code)."""

    pattern: str = Field(..., min_length=1, max_length=600)
    repl: str = Field(default="", max_length=2000)
    flags: int = Field(default=0, ge=0, le=10_000)


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
    governance_rule_packs: Optional[List[str]] = Field(
        default=None,
        description="Optional named governance rule packs (server-defined presets). Default off.",
        max_length=20,
    )
    governance_regex_rules: Optional[List[GovernanceRegexRule]] = Field(
        default=None,
        description="Additional regex cleanup rules (stored in metadata.pipeline.governance.regex_rules).",
        max_length=60,
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
    governance_pii_max_hits: Optional[int] = Field(
        default=None,
        ge=0,
        le=1_000_000,
        description="Max allowed PII matches per document before drop/quarantine (sum across kinds). None disables gate.",
    )
    governance_secrets_redact: Optional[bool] = Field(default=None, description="Redact common secrets/tokens (API keys, private keys, bearer tokens)")
    governance_secrets_mode: Optional[str] = Field(default=None, description="Secrets redaction mode: mask | token")
    governance_secrets_mask: Optional[str] = Field(default=None, description="Secrets replacement string (mask mode)")
    governance_secrets_max_hits: Optional[int] = Field(
        default=None,
        ge=0,
        le=1_000_000,
        description="Max allowed secrets matches per document before drop/quarantine (sum across kinds). None disables gate.",
    )
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
    chunk_merge_small_min_chars: Optional[int] = Field(
        default=None,
        ge=0,
        le=10_000,
        description="Optional: merge chunks shorter than this threshold with neighbors (0 disables).",
    )
    chunk_strategy_params: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Chunking strategy parameters (best-effort, strategy-specific). "
            "Only small JSON objects are allowed (primitive values only)."
        ),
    )
    embedding_context_prefix_enabled: Optional[bool] = Field(
        default=None,
        description="Prefix chunk content with lightweight structural context (e.g. header_path) before embedding (vector-only).",
    )
    chunk_vector_enabled: Optional[bool] = None
    bm25_index_enabled: Optional[bool] = None
    kg_enabled: Optional[bool] = None
    event_vector_enabled: Optional[bool] = None
    entity_vector_enabled: Optional[bool] = None
    # Structured/table ingestion (TAG - Table Augmented Generation).
    # When enabled, supported table-like documents (.csv/.xls/.xlsx) are imported into a per-document
    # SQLite table store and can be queried via SQL / NL-to-SQL (separate endpoints).
    table_store_enabled: Optional[bool] = Field(default=None, description="Enable structured table store import for .csv/.xls/.xlsx (TAG)")
    table_store_max_rows: Optional[int] = Field(default=None, ge=0, le=5_000_000, description="Max rows to import per table (0 disables cap)")
    table_store_max_cols: Optional[int] = Field(default=None, ge=0, le=10_000, description="Max columns to import per table (0 disables cap)")
    table_store_sample_rows: Optional[int] = Field(default=None, ge=0, le=200, description="Rows to keep for metadata preview/sample (0 disables)")
    # Auto routing (optional): when enabled, decide per-file whether to use TAG (table_store) or
    # normal parsing+RAG based on size/complexity signals.
    table_store_auto_route: Optional[bool] = Field(
        default=None,
        description="When table_store_enabled=true, auto-route small tables to RAG and large/complex tables to TAG",
    )
    table_store_auto_row_threshold: Optional[int] = Field(
        default=None,
        ge=0,
        le=50_000_000,
        description="In auto-route mode, route to TAG when estimated rows >= threshold (0 disables)",
    )
    table_store_auto_col_threshold: Optional[int] = Field(
        default=None,
        ge=0,
        le=200_000,
        description="In auto-route mode, route to TAG when estimated columns >= threshold (0 disables)",
    )
    table_store_auto_sheet_threshold: Optional[int] = Field(
        default=None,
        ge=0,
        le=200_000,
        description="In auto-route mode, route to TAG when sheet_count >= threshold (0 disables)",
    )
    table_store_auto_file_bytes_threshold: Optional[int] = Field(
        default=None,
        ge=0,
        le=5_000_000_000,
        description="In auto-route mode, route to TAG when file_size bytes >= threshold (0 disables)",
    )

    @model_validator(mode="after")
    def _validate_chunk_strategy_params(self) -> "DocumentPipelineOptions":
        """
        Security guard: keep `chunk_strategy_params` declarative and small.

        This payload can originate from:
        - API clients (pipeline JSON / patch)
        - dataset ingestion policy pipeline_patch
        """
        raw = self.chunk_strategy_params
        if raw is None:
            return self
        if not isinstance(raw, dict):
            raise ValueError("chunk_strategy_params must be an object")
        if len(raw) > 30:
            raise ValueError("chunk_strategy_params has too many keys (max=30)")

        cleaned: dict[str, Any] = {}
        for k, v in raw.items():
            if not isinstance(k, str):
                raise ValueError("chunk_strategy_params keys must be strings")
            key = k.strip()
            if not key:
                continue
            if len(key) > 80:
                raise ValueError("chunk_strategy_params key too long (max=80)")

            # Keep values primitive-only (no nested objects/lists).
            if v is None or isinstance(v, (bool, int, float)):
                cleaned[key] = v
                continue
            if isinstance(v, str):
                if len(v) > 500:
                    raise ValueError("chunk_strategy_params string value too long (max=500)")
                cleaned[key] = v
                continue
            raise ValueError("chunk_strategy_params values must be JSON primitives")

        self.chunk_strategy_params = cleaned or None
        return self


DocumentAccessMode = Literal["inherit", "only_me", "all_team_members", "partial_members"]


class DocumentAccessInfo(BaseModel):
    """Document-level ACL (additional restriction on top of dataset permissions)."""

    mode: DocumentAccessMode = "inherit"
    owner_id: Optional[str] = Field(default=None, max_length=255)
    partial_member_list: Optional[List[str]] = Field(default=None, max_length=200)


class DocumentAccessUpdateRequest(BaseModel):
    """Update a document's access mode and optional allowlist."""

    mode: DocumentAccessMode = Field(default="inherit")
    partial_member_list: Optional[List[str]] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _normalize(self) -> "DocumentAccessUpdateRequest":
        # Normalize member ids (trim/dedupe).
        if self.partial_member_list is not None:
            seen: set[str] = set()
            normalized: list[str] = []
            for raw in self.partial_member_list:
                mid = str(raw or "").strip()
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                if len(mid) > 255:
                    raise ValueError("partial_member_list member id too long (max=255)")
                normalized.append(mid)
                if len(normalized) >= 200:
                    break
            self.partial_member_list = normalized

        # Non-partial modes ignore allowlist (server will clear).
        if self.mode != "partial_members":
            self.partial_member_list = None
        return self


class DocumentPipelinePatchRequest(BaseModel):
    """
    Patch `documents.metadata.pipeline` (document-level pipeline overrides).

    - When `replace=false` (default), apply only fields provided in `patch`.
      - Any field explicitly set to `null` will clear that override (revert to defaults).
    - When `replace=true`, replace the whole pipeline override with `patch`.
    """

    patch: DocumentPipelineOptions = Field(
        default_factory=DocumentPipelineOptions,
        description="Pipeline patch; null values clear overrides (when field is present).",
    )
    replace: bool = Field(default=False, description="Replace entire pipeline override instead of patching")


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


class DocumentBatchLifecycleRequest(BaseModel):
    """Batch document lifecycle update (enable/disable/archive/unarchive)."""

    document_ids: List[UUID] = Field(..., min_length=1, max_length=200)


class DocumentBatchLifecycleResponse(BaseModel):
    """Batch lifecycle update result."""

    updated: int
    not_found: List[UUID] = Field(default_factory=list)
    denied: List[UUID] = Field(default_factory=list)
    conflicts: List[UUID] = Field(default_factory=list)


class DocumentBatchDeleteRequest(BaseModel):
    """Batch delete documents."""

    document_ids: List[UUID] = Field(..., min_length=1, max_length=200)


class DocumentBatchDeleteResponse(BaseModel):
    """Batch delete result."""

    deleted: int
    not_found: List[UUID] = Field(default_factory=list)
    denied: List[UUID] = Field(default_factory=list)


class DocumentBatchRetryRequest(BaseModel):
    """Batch retry document ingestion (reprocess)."""

    document_ids: List[UUID] = Field(..., min_length=1, max_length=200)
    force: bool = False
    skip_if_unchanged: bool = False


class DocumentBatchReingestRequest(BaseModel):
    """
    Batch re-ingest documents (patch pipeline then retry).

    Intended for pipeline version regeneration and index rebuilds:
    - update `documents.metadata.pipeline` overrides (optional)
    - trigger `/documents/{id}/retry` with `force` (default true)
    """

    document_ids: List[UUID] = Field(..., min_length=1, max_length=200)
    patch: DocumentPipelineOptions = Field(default_factory=DocumentPipelineOptions)
    replace: bool = False
    force: bool = True
    skip_if_unchanged: bool = False


class DocumentBatchRetryResponse(BaseModel):
    """Batch retry result."""

    queued: int
    skipped: int
    not_found: List[UUID] = Field(default_factory=list)
    denied: List[UUID] = Field(default_factory=list)
    conflicts: List[UUID] = Field(default_factory=list)


class DocumentBatchMoveRequest(BaseModel):
    """Batch move documents between datasets (best-effort)."""

    document_ids: List[UUID] = Field(..., min_length=1, max_length=200)
    target_dataset_id: Optional[UUID] = None


class DocumentBatchMoveResponse(BaseModel):
    """Batch move result."""

    moved: int
    not_found: List[UUID] = Field(default_factory=list)
    denied: List[UUID] = Field(default_factory=list)
    conflicts: List[UUID] = Field(default_factory=list)


class DocumentBatchAccessUpdateRequest(BaseModel):
    """Batch update document-level ACL."""

    document_ids: List[UUID] = Field(..., min_length=1, max_length=200)
    access: DocumentAccessUpdateRequest


class DocumentBatchAccessUpdateResponse(BaseModel):
    """Batch ACL update result."""

    updated: int
    not_found: List[UUID] = Field(default_factory=list)
    denied: List[UUID] = Field(default_factory=list)


class DuplicateDocumentItem(BaseModel):
    """Document info in a duplicate group (by file_sha256)."""

    id: UUID
    filename: str
    status: str
    dataset_id: Optional[UUID] = None
    created_at: datetime


class DocumentDuplicateGroup(BaseModel):
    file_sha256: str
    count: int
    documents: List[DuplicateDocumentItem] = Field(default_factory=list)


class DocumentDuplicateList(BaseModel):
    total: int
    items: List[DocumentDuplicateGroup] = Field(default_factory=list)


class DocumentChunkSchema(OrmModel):
    """Document chunk."""
    id: UUID
    content: str
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    chunk_index: int
    disabled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("doc_metadata", "metadata"),
    )


class DocumentChunkUpdateRequest(BaseModel):
    """
    Patch a document chunk.

    Notes:
    - This is used for post-ingest manual chunk editing (no re-parse required).
    - metadata is a patch dict: keys with null values are removed.
    """

    content: Optional[str] = Field(default=None, max_length=200_000)
    page_number: Optional[int] = Field(default=None, ge=0, le=100_000)
    start_char: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    end_char: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Chunk metadata patch (null values delete keys)")


class DocumentChunkCreateRequest(BaseModel):
    """Create a new chunk (appends to the active pipeline version)."""

    content: str = Field(..., min_length=1, max_length=200_000)
    page_number: Optional[int] = Field(default=None, ge=0, le=100_000)
    start_char: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    end_char: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentChunkReembedRequest(BaseModel):
    """Re-embed (re-index) selected chunks for a document."""

    chunk_ids: List[UUID] = Field(..., min_length=1, max_length=200)
    include_disabled: bool = False


class DocumentChunkReembedResponse(BaseModel):
    """Re-embed result."""

    reembedded: int
    not_found: List[UUID] = Field(default_factory=list)
    denied: List[UUID] = Field(default_factory=list)
    conflicts: List[UUID] = Field(default_factory=list)


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
    owner_id: Optional[str] = None
    access_mode: Optional[DocumentAccessMode] = None
    archived_at: Optional[datetime] = None
    disabled_at: Optional[datetime] = None
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


class DocumentParsedContentResponse(BaseModel):
    """Persisted parsed markdown content for a document (best-effort).

    Notes:
    - This is only available when the ingestion pipeline enables `persist_parsed_content`.
    - The returned markdown is already truncated when persisted (pipeline-controlled), and may be further
      truncated by the API handler via `max_chars` for UI safety.
    """

    document_id: UUID
    available: bool = False
    markdown_content: str = Field(default="")
    original_markdown_content: str = Field(default="")
    # Best-effort metadata copied from `document.metadata.parsed_content_persisted`.
    persisted_meta: Dict[str, Any] = Field(default_factory=dict)
    markdown_truncated: bool = False
    original_markdown_truncated: bool = False
    max_chars: int = Field(default=200_000, ge=0, le=2_000_000)


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


class DocumentStats(BaseModel):
    """Document stats for knowledge-base dashboards."""

    total: int
    by_status: Dict[str, int] = Field(default_factory=dict)
    total_chunks: int = 0
    total_size: int = 0


class DocumentChunkMatch(BaseModel):
    """Lightweight chunk match entry (for search/navigation without loading full content)."""

    id: UUID
    chunk_index: int
    page_number: Optional[int] = None


class DocumentChunkMatchList(BaseModel):
    """Paged (and possibly truncated) chunk match list."""

    total: int
    truncated: bool = False
    items: List[DocumentChunkMatch] = Field(default_factory=list)


class DocumentChunkList(BaseModel):
    """Paged document chunks."""
    total: int
    items: List[DocumentChunkSchema]


class DocumentVersionInfo(BaseModel):
    """A document processing/version entry (keyed by pipeline_hash)."""

    pipeline_hash: str
    doc_pipeline_key: str
    chunk_count: int = 0
    first_chunk_at: Optional[datetime] = None
    last_chunk_at: Optional[datetime] = None
    active: bool = False


class DocumentVersionList(BaseModel):
    """List document versions (pipeline history)."""

    document_id: UUID
    active_pipeline_hash: Optional[str] = None
    pipeline_hash: Optional[str] = None
    items: List[DocumentVersionInfo] = Field(default_factory=list)


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
    # Note: for langchain_token strategy this is interpreted as tokens; otherwise chars.
    chunk_size: int = Field(default=1000, ge=50, le=4000, description="Chunk size")
    chunk_overlap: int = Field(default=200, ge=0, le=1000, description="Overlap size")
    unit: str = Field(default="chars", description="chunk_size/chunk_overlap unit: chars | tokens")
    strategy_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Best-effort strategy-specific params for reproducibility (e.g. separator/parent_child).",
    )


class ChunkPreviewItem(BaseModel):
    """Chunk preview item."""
    index: int
    content: str
    length: int
    # Approximate token count for UI display/stats (token-mode uses tiktoken when available).
    tokens_est: Optional[int] = None
    start_index: int  # Start position in original text.
    end_index: int    # End position in original text.
    page_number: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChunkPreviewStats(BaseModel):
    """Lightweight aggregate stats for UI (computed on returned chunks)."""

    unit: Literal["chars", "tokens"] = "chars"
    count: int = 0
    total: int = 0
    min: int = 0
    max: int = 0
    avg: int = 0
    median: int = 0
    p10: int = 0
    p90: int = 0
    total_tokens_est: int = 0
    short_count: int = 0
    duplicate_count: int = 0
    # Coverage signals (chars-based; uses start/end indices).
    sum_chunk_chars: int = 0
    covered_chars: int = 0
    coverage_ratio: float = 0.0
    overlap_waste_ratio: float = 0.0
    gap_count: int = 0
    largest_gap: int = 0


class ChunkPreviewQualityGate(BaseModel):
    """Best-effort quality gate for enterprise tuning (heuristics)."""

    grade: Literal["pass", "warn", "fail"] = "pass"
    reasons: List[str] = Field(default_factory=list)


class ChunkPreviewRecommendationPatch(BaseModel):
    """Structured, actionable recommendation (best-effort)."""

    target: Literal["preview", "pipeline", "perf"] = "preview"
    id: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    patch: Dict[str, Any] = Field(default_factory=dict, description="Patch object; shape depends on target.")


class ChunkPreviewReviewSignals(BaseModel):
    """Optional per-chunk review signals for enterprise tuning/auditing."""

    basis: Literal["all", "child"] = "all"
    short_indices: List[int] = Field(default_factory=list)
    duplicate_indices: List[int] = Field(default_factory=list)
    gap_indices: List[int] = Field(default_factory=list)
    overlap_indices: List[int] = Field(default_factory=list)
    # Optional details (best-effort; keys are chunk indices).
    gap_before_by_index: Dict[int, int] = Field(default_factory=dict)
    overlap_prev_by_index: Dict[int, int] = Field(default_factory=dict)


class ChunkPreviewResponse(BaseModel):
    """Chunk preview response."""
    filename: str
    file_type: str
    file_size: int
    # SHA256 of the uploaded file content (for client-side correlation / caching).
    file_sha256: Optional[str] = None
    # Best-effort parse cache signals (server-side, per-process).
    parse_cache_hit: bool = False
    parse_cache_age_ms: Optional[int] = None
    # Server-side elapsed time (best-effort; excludes network).
    preview_duration_ms: Optional[int] = None
    # Optional stage timings (best-effort; excludes network).
    upload_duration_ms: Optional[int] = None
    parse_duration_ms: Optional[int] = None
    governance_duration_ms: Optional[int] = None
    chunking_duration_ms: Optional[int] = None
    stats_duration_ms: Optional[int] = None
    total_chunks: int
    # When max_chunks is used, the API may truncate returned chunks; this keeps the original count.
    total_chunks_full: int = 0
    chunks_truncated: bool = False
    chunks_max_count: int = 0
    total_characters: int
    params: ChunkPreviewParams
    chunks: List[ChunkPreviewItem]
    stats: Optional[ChunkPreviewStats] = None
    # When using chunk_strategy=auto, return the most common selected strategy (best-effort).
    auto_selected_strategy: Optional[str] = None
    # Non-fatal warnings for UI (e.g. ignored overlap for separator strategy).
    warnings: List[str] = Field(default_factory=list)
    # Optional per-chunk review signals (gated by include_review_signals).
    review_signals: Optional[ChunkPreviewReviewSignals] = None
    # Best-effort quality gate and actionable recommendations.
    quality_gate: Optional[ChunkPreviewQualityGate] = None
    recommendations: List[str] = Field(default_factory=list)
    recommendation_patches: List[ChunkPreviewRecommendationPatch] = Field(default_factory=list)
    # Original text for frontend highlighting.
    original_text: Optional[str] = None
    # If original_text contains PDF position tags (e.g. @@page\tl\tr\tt\tb##), provide a cleaned version for UI display.
    original_text_cleaned: Optional[str] = None
    # Best-effort metadata for UI (whether original_text was omitted due to size limit).
    original_text_included: bool = False
    original_text_truncated: bool = False
    original_text_max_chars: int = 100000
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
    # Optional directory-preserving upload key (e.g. folder/sub/file.pdf). Used by the UI to
    # correlate results when multiple files share the same basename.
    source_path: str | None = None


class DocumentBatchUploadFailure(BaseModel):
    """Single file result for failed batch upload."""
    filename: str
    error: str
    source_path: str | None = None


class DocumentBatchUploadResponse(BaseModel):
    """Batch upload endpoint response."""
    total: int
    successful_count: int
    failed_count: int
    successful: List[DocumentBatchUploadSuccess] = Field(default_factory=list)
    failed: List[DocumentBatchUploadFailure] = Field(default_factory=list)
