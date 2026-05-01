"""
Document processing pipeline schemas.
Defines data models for document parsing, chunking, and other pipeline operations.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ImageInfo(BaseModel):
    id: str
    url: str
    filename: str


class PDFQualityScore(BaseModel):
    """
    PDF quality score (sampled from first 3 pages).

    Scoring dimensions:
    - text_quality_score (50%): Text extraction quality
    - format_consistency_score (30%): Format consistency
    - table_quality_score (20%): Table completeness
    """
    score: float = Field(..., description="Overall score 0-1, higher is cleaner")
    text_quality_score: float = Field(..., description="Text extraction quality (0-1)")
    format_consistency_score: float = Field(..., description="Format consistency (0-1)")
    table_quality_score: float = Field(..., description="Table completeness (0-1)")
    reading_order_score: float | None = Field(default=None, description="Reading-order consistency (0-1)")
    is_scanned: bool = Field(..., description="Whether it is a scanned document")
    page_count: float = Field(..., description="Total page count")


class ParsePreviewResponse(BaseModel):
    backend: str
    pdf_quality: PDFQualityScore | None = None
    markdown: str
    images: list[ImageInfo] = Field(default_factory=list)


class PreprocessStepLog(BaseModel):
    id: str
    applied: bool
    changed: bool
    note: str = ""
    bytes_before: int = 0
    bytes_after: int = 0
    elapsed_ms: int = 0


class PreprocessSummary(BaseModel):
    changed: bool = False
    size_before: int = 0
    size_after: int = 0
    steps: list[PreprocessStepLog] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class IngestionPreviewRule(BaseModel):
    matched: bool = False
    rule_id: str | None = None
    rule_name: str | None = None
    governance_profile_ref: str | None = None
    preprocess_steps: list[dict[str, Any]] = Field(default_factory=list)
    parser_backend: str = "auto"
    chunk_strategy: str = ""


class IngestionPreviewResponse(BaseModel):
    rule: IngestionPreviewRule
    preprocess: PreprocessSummary
    parse: ParsePreviewResponse
    clean: CleanPreviewResponse
    # Explain payload for UI export/auditing (best-effort; does not affect ingestion).
    explain: dict[str, Any] = Field(default_factory=dict)


class ChunkItem(BaseModel):
    id: str
    level: str
    index: int
    text: str
    start: int
    end: int
    tokens_est: int
    parent_id: str | None = None


class PipelineChunkPreviewRequest(BaseModel):
    markdown: str


class PipelineChunkPreviewResponse(BaseModel):
    paragraphs: list[ChunkItem]
    sentences: list[ChunkItem]


class CleanRegexRuleModel(BaseModel):
    pattern: str
    repl: str = ""
    flags: int = 0


class CleanPreviewRuleStat(BaseModel):
    index: int = Field(..., ge=0)
    pattern: str
    repl: str = ""
    flags: int = 0
    hits: int = Field(default=0, ge=0, le=10_000_000)
    source: str | None = Field(default=None, description="Rule source: default | pack | custom", max_length=32)
    pack: str | None = Field(default=None, description="When source=pack, the pack key", max_length=64)


class GovernanceIssue(BaseModel):
    code: str = Field(..., min_length=1, max_length=100)
    severity: Literal["info", "warning", "error"] = "info"
    message: str = Field(..., min_length=1, max_length=400)
    count: int = Field(default=0, ge=0, le=10_000_000)
    samples: list[str] = Field(default_factory=list, description="Best-effort samples (may be truncated)")
    suggested_pipeline_patch: dict[str, Any] = Field(
        default_factory=dict,
        description="Best-effort suggested pipeline patch (DocumentPipelineOptions shape).",
    )


class GovernanceCommonLineCandidate(BaseModel):
    signature: str = Field(..., min_length=1, max_length=400)
    sample: str = Field(default="", max_length=400)
    docs: int = Field(default=0, ge=0, le=1_000_000)
    ratio: float = Field(default=0.0, ge=0.0, le=1.0)


class GovernanceCommonLinesLearnRequest(BaseModel):
    dataset_id: UUID
    limit_docs: int = Field(default=20, ge=2, le=50)
    use_original: bool = Field(
        default=True,
        description="Prefer DocumentParsedContent.original_markdown_content (pre-governance) when available.",
    )
    min_docs: int = Field(default=3, ge=2, le=50)
    min_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    max_line_length: int = Field(default=120, ge=20, le=400)
    max_candidates: int = Field(default=50, ge=1, le=200)


class GovernanceCommonLinesLearnResponse(BaseModel):
    dataset_id: UUID
    total_documents: int = 0
    used_documents: int = 0
    candidates: list[GovernanceCommonLineCandidate] = Field(default_factory=list)


class CleanPreviewRequest(BaseModel):
    markdown: str
    rules: list[CleanRegexRuleModel] = Field(default_factory=list)
    rule_packs: list[str] = Field(
        default_factory=list,
        description="Optional named governance rule packs (server-defined presets). Default off.",
        max_length=20,
    )
    use_default_rules: bool = True
    # When enabled, return a unified diff (text) between input and output (best-effort, may be truncated).
    include_diff: bool = False
    diff_max_lines: int = Field(default=2000, ge=0, le=20000)
    # How to interpret `markdown` input (some governance steps can operate on raw HTML).
    input_format: Literal["markdown", "html"] = "markdown"
    # When input_format=html, optionally extract specific nodes via XPath before converting to text.
    html_xpath: str | None = None
    normalize_line_endings: bool = True
    trim_trailing_spaces: bool = True
    collapse_blank_lines: bool = True
    # Maximum consecutive blank lines to keep (0 = no blank lines; 1 = default; 2 = allow two blank lines).
    max_blank_lines: int = Field(default=1, ge=0, le=10)
    remove_control_chars: bool = True
    remove_toc_lines: bool = True
    remove_noise_lines: bool = True
    remove_common_lines: bool = True
    unwrap_lines: bool = True
    # Remove common boilerplate blocks (ads/navigation/acknowledgements/disclaimers/copyright).
    remove_boilerplate: bool = False
    # Image cleanup:
    # - none: keep all images
    # - decorative: remove likely decorative images (logos/qrcodes/banners)
    # - all: remove all image tags/refs
    remove_images: Literal["none", "decorative", "all"] = "none"
    # Frontmatter extraction (Markdown only):
    extract_frontmatter: bool = False
    strip_frontmatter: bool = False
    # Language detection (metadata only):
    detect_language: bool = False
    language_min_chars: int = Field(default=40, ge=0, le=200_000)
    # URL normalization:
    normalize_urls: bool = False
    normalize_urls_strip_tracking: bool = True
    # Paragraph-level duplicate dropping:
    drop_duplicate_paragraphs: bool = False
    drop_duplicate_paragraphs_min_occurrences: int = Field(default=3, ge=2, le=100)
    drop_duplicate_paragraphs_min_chars: int = Field(default=40, ge=0, le=50_000)
    drop_duplicate_paragraphs_max_chars: int = Field(default=1200, ge=0, le=200_000)
    # Trim trailing references/bibliography section:
    trim_references: bool = False
    # Keyword extraction (metadata only):
    extract_keywords: bool = False
    keywords_provider: str = Field(default="auto")
    keywords_top_k: int = Field(default=10, ge=1, le=100)
    keywords_max_chars: int = Field(default=20000, ge=0, le=200_000)
    # Optional normalization:
    normalize_tables: bool = False
    # Remove leading line numbers within fenced code blocks (best-effort heuristic).
    strip_code_line_numbers: bool = False
    # PII anonymization (independent of global PII middleware):
    pii_anonymize: bool = False
    pii_mode: Literal["mask", "token"] = "mask"
    pii_mask: str = Field(default="[REDACTED]", min_length=1, max_length=64)
    # Secrets/token redaction (API keys, private keys, bearer tokens...):
    secrets_redact: bool = False
    secrets_mode: Literal["mask", "token"] = "mask"
    secrets_mask: str = Field(default="[SECRET]", min_length=1, max_length=64)
    # Document-level filters:
    drop_outline_only: bool = False
    drop_outline_min_content_chars: int = Field(default=200, ge=0, le=200_000)
    drop_outline_max_heading_ratio: float = Field(default=0.85, ge=0.0, le=1.0)
    drop_low_density: bool = False
    drop_low_density_threshold: float = Field(default=0.12, ge=0.0, le=1.0)
    unwrap_max_line_length: int = Field(default=120, ge=40, le=400)
    noise_min_chars: int = Field(default=2, ge=1, le=20)
    noise_ratio_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    common_lines_min_occurrences: int = Field(default=3, ge=2, le=30)


class CleanPreviewResponse(BaseModel):
    markdown: str
    applied_rules: int
    changed: bool
    rule_stats: list[CleanPreviewRuleStat] = Field(default_factory=list)
    dropped: bool = False
    drop_reason: str | None = None
    pii_hits: dict[str, int] | None = None
    secrets_hits: dict[str, int] | None = None
    # Optional extracted metadata (preview only; not persisted).
    frontmatter: dict[str, Any] | None = None
    title: str | None = None
    tags: list[str] | None = None
    language: str | None = None
    language_confidence: float | None = None
    keywords: list[str] | None = None
    urls_changed: int = 0
    paragraphs_dropped: int = 0
    references_removed_lines: int = 0
    # High-level diff/stats to help tune governance parameters.
    input_chars: int = 0
    output_chars: int = 0
    input_lines: int = 0
    output_lines: int = 0
    added_lines: int = 0
    removed_lines: int = 0
    changed_lines: int = 0
    diff_unified: str | None = None
    diff_truncated: bool = False
    issues: list[GovernanceIssue] = Field(default_factory=list)
    suggested_pipeline_patch: dict[str, Any] = Field(default_factory=dict)


class CleanRulesResponse(BaseModel):
    rules: list[CleanRegexRuleModel]


class KeywordExtractRequest(BaseModel):
    text: str
    provider: str = Field(default="jieba")
    top_k: int = Field(default=10, ge=1, le=50)


class KeywordExtractResponse(BaseModel):
    provider: str
    keywords: list[str] = Field(default_factory=list)


class AutoAnnotationRequest(BaseModel):
    text: str = Field(..., description="Text to inspect for reviewable annotation candidates.")
    mode: Literal["document_focus", "compliance"] = Field(
        default="document_focus",
        description="document_focus extracts important document spans; compliance exposes PII/secret/entity detectors.",
    )
    providers: list[Literal["cpu", "llm", "gliner", "keyword", "entity", "regex", "pii", "secret", "sensitive"]] | None = Field(
        default=None,
        description="Optional explicit provider list. When omitted, legacy enable_* switches decide providers.",
        max_length=20,
    )
    enable_llm: bool = Field(default=False, description="Use configured LLM first for document_focus mode.")
    enable_llm_topics: bool = Field(default=False, description="Return LLM document-level semantic tags when available.")
    llm_model: str | None = Field(default=None, max_length=120)
    enable_keywords: bool = True
    enable_entities: bool = True
    enable_sensitive: bool = False
    keyword_provider: str = Field(default="simple", max_length=32)
    keyword_top_k: int = Field(default=12, ge=1, le=50)
    max_chars: int = Field(default=20000, ge=1, le=200_000)
    max_annotations: int = Field(default=80, ge=1, le=500)


class AutoAnnotationItem(BaseModel):
    text: str
    type: Literal["entity", "keyword", "sensitive", "custom"]
    label: str
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str = Field(
        default="keyword",
        description="Detector source, e.g. keyword, regex_entity, pii, secret.",
        max_length=64,
    )


class AutoDocumentTag(BaseModel):
    type: Literal["topic", "category", "domain", "industry", "doc_type", "sensitivity", "quality", "keyword"]
    value: str = Field(..., min_length=1, max_length=120)
    label: str = Field(default="", max_length=80)
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    source: str = Field(default="llm", max_length=64)


class AutoAnnotationResponse(BaseModel):
    annotations: list[AutoAnnotationItem] = Field(default_factory=list)
    document_tags: list[AutoDocumentTag] = Field(default_factory=list)
    summary: str | None = None
    text_chars: int = Field(default=0, ge=0)
    scanned_chars: int = Field(default=0, ge=0)
    truncated: bool = False
    keyword_provider: str | None = None
    strategy: Literal["llm", "rules", "hybrid"] = "rules"
    providers_used: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LLMCleanPreviewRequest(BaseModel):
    markdown: str
    prompt_template_id: UUID | None = None
    template_key: str | None = None
    ab_experiment_key: str | None = None
    ab_user_key: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=16, le=32768)
    max_chars: int = Field(default=15000, ge=1000, le=200000)


class LLMCleanPreviewResponse(BaseModel):
    markdown: str
    changed: bool
    model_used: str | None = None
    prompt_template_id: str | None = None
    template_key: str | None = None
    ab_experiment_key: str | None = None
    ab_variant: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ParserBackendInfo(BaseModel):
    name: str
    available: bool
    notes: str | None = None


class ChunkStrategyInfo(BaseModel):
    name: str
    available: bool
    notes: str | None = None


class PipelineCapabilitiesResponse(BaseModel):
    default_parser_backend: str
    default_chunk_strategy: str
    pdf_backends: list[ParserBackendInfo] = Field(default_factory=list)
    chunk_strategies: list[ChunkStrategyInfo] = Field(default_factory=list)


class GovernanceAnalyzeRequest(BaseModel):
    markdown: str
    input_format: Literal["markdown", "html"] = "markdown"
    html_xpath: str | None = None
    remove_images: Literal["none", "decorative", "all"] = "none"

    # Current (or intended) governance toggles; used to generate non-redundant suggestions.
    remove_control_chars: bool = True
    unwrap_lines: bool = True
    remove_common_lines: bool = True
    remove_boilerplate: bool = False
    normalize_tables: bool = False
    normalize_urls: bool = False
    normalize_urls_strip_tracking: bool = True
    drop_outline_only: bool = False
    drop_outline_min_content_chars: int = Field(default=200, ge=0, le=200_000)
    drop_outline_max_heading_ratio: float = Field(default=0.85, ge=0.0, le=1.0)
    drop_low_density: bool = False
    drop_low_density_threshold: float = Field(default=0.12, ge=0.0, le=1.0)


class GovernanceAnalyzeResponse(BaseModel):
    input_chars: int = 0
    input_lines: int = 0
    issues: list[GovernanceIssue] = Field(default_factory=list)
    suggested_pipeline_patch: dict[str, Any] = Field(default_factory=dict)


class ZipImageInfo(BaseModel):
    img_id: str
    original_path: str
    url: str


class ZipWithImagesResponse(BaseModel):
    markdown: str
    images: list[ZipImageInfo] = Field(default_factory=list)
    image_count: int
    dataset_id: str
    document_id: str
