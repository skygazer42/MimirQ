"""
Internal configuration types for document pipeline (not API Schema)

Notes:
- PipelineOptions/PipelineEffective are internal structures used by service layer when parsing doc_metadata and settings
- Should not be placed in app/api/schemas (avoid polluting API schema layer with internal config)
"""


from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PipelineOptions:
    governance_enabled: bool | None = None
    governance_remove_toc_lines: bool | None = None
    governance_remove_noise_lines: bool | None = None
    governance_unwrap_lines: bool | None = None
    governance_remove_common_lines: bool | None = None
    governance_remove_boilerplate: bool | None = None
    governance_remove_images: str | None = None
    # Optional named rule packs (server-defined). Default off; must be explicitly enabled.
    governance_rule_packs: list[str] | None = None
    # Additional regex cleanup rules stored in metadata.pipeline.governance.regex_rules (best-effort).
    governance_regex_rules: list[dict] | None = None
    governance_extract_frontmatter: bool | None = None
    governance_strip_frontmatter: bool | None = None
    governance_detect_language: bool | None = None
    governance_language_min_chars: int | None = None
    governance_normalize_urls: bool | None = None
    governance_normalize_urls_strip_tracking: bool | None = None
    governance_drop_duplicate_paragraphs: bool | None = None
    governance_drop_duplicate_paragraphs_min_occurrences: int | None = None
    governance_drop_duplicate_paragraphs_min_chars: int | None = None
    governance_drop_duplicate_paragraphs_max_chars: int | None = None
    governance_trim_references: bool | None = None
    governance_extract_keywords: bool | None = None
    governance_keywords_provider: str | None = None
    governance_keywords_top_k: int | None = None
    governance_keywords_max_chars: int | None = None
    governance_normalize_tables: bool | None = None
    governance_strip_code_line_numbers: bool | None = None
    governance_quarantine_on_drop: bool | None = None
    governance_pii_anonymize: bool | None = None
    governance_pii_mode: str | None = None
    governance_pii_mask: str | None = None
    governance_pii_max_hits: int | None = None
    governance_secrets_redact: bool | None = None
    governance_secrets_mode: str | None = None
    governance_secrets_mask: str | None = None
    governance_secrets_max_hits: int | None = None
    governance_max_blank_lines: int | None = None
    governance_html_xpath: str | None = None
    governance_drop_outline_only: bool | None = None
    governance_drop_outline_min_content_chars: int | None = None
    governance_drop_outline_max_heading_ratio: float | None = None
    governance_drop_low_density: bool | None = None
    governance_drop_low_density_threshold: float | None = None
    governance_unwrap_max_line_length: int | None = None
    governance_noise_min_chars: int | None = None
    governance_noise_ratio_threshold: float | None = None
    governance_common_lines_min_docs: int | None = None
    governance_common_lines_min_ratio: float | None = None
    parse_fallback_enabled: bool | None = None
    parse_fallback_min_content_chars: int | None = None
    parse_fallback_min_parse_score: float | None = None
    parse_fallback_max_retries: int | None = None
    cross_page_merge_enabled: bool | None = None
    cross_page_merge_max_page_gap: int | None = None
    reading_order_enabled: bool | None = None
    parse_cache_enabled: bool | None = None
    parse_cache_ttl_sec: int | None = None
    vlm_correction_enabled: bool | None = None
    vlm_correction_min_table_score: float | None = None
    vlm_correction_max_pages: int | None = None
    persist_parsed_content: bool | None = None
    persist_parsed_content_max_chars: int | None = None
    near_dedup_enabled: bool | None = None
    near_dedup_hamming_threshold: int | None = None
    near_dedup_max_bucket_size: int | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    chunk_merge_small_min_chars: int | None = None
    # Strategy-specific chunking params (best-effort; kept small & declarative by API validation).
    chunk_strategy_params: dict[str, Any] | None = None
    # When enabled, prefix chunk content with lightweight structural context (e.g. header_path)
    # before computing embeddings. Does not change stored chunk.content (DB); affects vector similarity only.
    embedding_context_prefix_enabled: bool | None = None
    # When enabled, inject a short document/section-level context prefix before embedding (vector-only).
    # This is a deterministic heuristic by default; does not change stored chunk.content (DB).
    embedding_contextual_retrieval_enabled: bool | None = None
    # When enabled, store extra field-aware embeddings (title/heading) alongside the body embedding.
    # This is dataset-scoped and increases vector write volume.
    embedding_field_aware_enabled: bool | None = None
    chunk_vector_enabled: bool | None = None
    bm25_index_enabled: bool | None = None
    kg_enabled: bool | None = None
    event_vector_enabled: bool | None = None
    entity_vector_enabled: bool | None = None
    # Structured/table store (TAG).
    table_store_enabled: bool | None = None
    table_store_max_rows: int | None = None
    table_store_max_cols: int | None = None
    table_store_sample_rows: int | None = None
    table_store_auto_route: bool | None = None
    table_store_sidecar_exclusive_routing: bool | None = None
    table_store_auto_row_threshold: int | None = None
    table_store_auto_col_threshold: int | None = None
    table_store_auto_sheet_threshold: int | None = None
    table_store_auto_file_bytes_threshold: int | None = None
    # Image understanding (caption/OCR). Conservative by default.
    image_caption_enabled: bool | None = None
    image_ocr_enabled: bool | None = None
    image_ocr_max_chars: int | None = None
    image_ocr_max_images: int | None = None


@dataclass(frozen=True)
class PipelineEffective:
    governance_enabled: bool
    governance_remove_toc_lines: bool
    governance_remove_noise_lines: bool
    governance_unwrap_lines: bool
    governance_remove_common_lines: bool
    governance_remove_boilerplate: bool
    governance_remove_images: str
    governance_rule_packs: list[str]
    governance_regex_rules: list[dict]
    governance_extract_frontmatter: bool
    governance_strip_frontmatter: bool
    governance_detect_language: bool
    governance_language_min_chars: int
    governance_normalize_urls: bool
    governance_normalize_urls_strip_tracking: bool
    governance_drop_duplicate_paragraphs: bool
    governance_drop_duplicate_paragraphs_min_occurrences: int
    governance_drop_duplicate_paragraphs_min_chars: int
    governance_drop_duplicate_paragraphs_max_chars: int
    governance_trim_references: bool
    governance_extract_keywords: bool
    governance_keywords_provider: str
    governance_keywords_top_k: int
    governance_keywords_max_chars: int
    governance_normalize_tables: bool
    governance_strip_code_line_numbers: bool
    governance_quarantine_on_drop: bool
    governance_pii_anonymize: bool
    governance_pii_mode: str
    governance_pii_mask: str
    governance_pii_max_hits: int
    governance_secrets_redact: bool
    governance_secrets_mode: str
    governance_secrets_mask: str
    governance_secrets_max_hits: int
    governance_max_blank_lines: int
    governance_html_xpath: str
    governance_drop_outline_only: bool
    governance_drop_outline_min_content_chars: int
    governance_drop_outline_max_heading_ratio: float
    governance_drop_low_density: bool
    governance_drop_low_density_threshold: float
    governance_unwrap_max_line_length: int
    governance_noise_min_chars: int
    governance_noise_ratio_threshold: float
    governance_common_lines_min_docs: int
    governance_common_lines_min_ratio: float
    parse_fallback_enabled: bool
    parse_fallback_min_content_chars: int
    parse_fallback_min_parse_score: float
    parse_fallback_max_retries: int
    cross_page_merge_enabled: bool
    cross_page_merge_max_page_gap: int
    reading_order_enabled: bool
    parse_cache_enabled: bool
    parse_cache_ttl_sec: int
    vlm_correction_enabled: bool
    vlm_correction_min_table_score: float
    vlm_correction_max_pages: int
    persist_parsed_content: bool
    persist_parsed_content_max_chars: int
    near_dedup_enabled: bool
    near_dedup_hamming_threshold: int
    near_dedup_max_bucket_size: int
    chunk_size: int
    chunk_overlap: int
    chunk_merge_small_min_chars: int
    chunk_strategy_params: dict[str, Any]
    embedding_context_prefix_enabled: bool
    embedding_contextual_retrieval_enabled: bool
    embedding_field_aware_enabled: bool
    chunk_vector_enabled: bool
    bm25_index_enabled: bool
    kg_enabled: bool
    event_vector_enabled: bool
    entity_vector_enabled: bool
    table_store_enabled: bool
    table_store_max_rows: int
    table_store_max_cols: int
    table_store_sample_rows: int
    table_store_auto_route: bool
    table_store_sidecar_exclusive_routing: bool
    table_store_auto_row_threshold: int
    table_store_auto_col_threshold: int
    table_store_auto_sheet_threshold: int
    table_store_auto_file_bytes_threshold: int
    image_caption_enabled: bool
    image_ocr_enabled: bool
    image_ocr_max_chars: int
    image_ocr_max_images: int


__all__ = [
    "PipelineEffective",
    "PipelineOptions",
]
