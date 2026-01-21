"""
Internal configuration types for document pipeline (not API Schema)

Notes:
- PipelineOptions/PipelineEffective are internal structures used by service layer when parsing doc_metadata and settings
- Should not be placed in app/api/schemas (avoid polluting API schema layer with internal config)
"""


from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PipelineOptions:
    governance_enabled: Optional[bool] = None
    governance_remove_toc_lines: Optional[bool] = None
    governance_remove_noise_lines: Optional[bool] = None
    governance_unwrap_lines: Optional[bool] = None
    governance_remove_common_lines: Optional[bool] = None
    governance_remove_boilerplate: Optional[bool] = None
    governance_remove_images: Optional[str] = None
    governance_extract_frontmatter: Optional[bool] = None
    governance_strip_frontmatter: Optional[bool] = None
    governance_detect_language: Optional[bool] = None
    governance_language_min_chars: Optional[int] = None
    governance_normalize_urls: Optional[bool] = None
    governance_normalize_urls_strip_tracking: Optional[bool] = None
    governance_drop_duplicate_paragraphs: Optional[bool] = None
    governance_drop_duplicate_paragraphs_min_occurrences: Optional[int] = None
    governance_drop_duplicate_paragraphs_min_chars: Optional[int] = None
    governance_drop_duplicate_paragraphs_max_chars: Optional[int] = None
    governance_trim_references: Optional[bool] = None
    governance_extract_keywords: Optional[bool] = None
    governance_keywords_provider: Optional[str] = None
    governance_keywords_top_k: Optional[int] = None
    governance_keywords_max_chars: Optional[int] = None
    governance_normalize_tables: Optional[bool] = None
    governance_strip_code_line_numbers: Optional[bool] = None
    governance_quarantine_on_drop: Optional[bool] = None
    governance_pii_anonymize: Optional[bool] = None
    governance_pii_mode: Optional[str] = None
    governance_pii_mask: Optional[str] = None
    governance_secrets_redact: Optional[bool] = None
    governance_secrets_mode: Optional[str] = None
    governance_secrets_mask: Optional[str] = None
    governance_max_blank_lines: Optional[int] = None
    governance_html_xpath: Optional[str] = None
    governance_drop_outline_only: Optional[bool] = None
    governance_drop_outline_min_content_chars: Optional[int] = None
    governance_drop_outline_max_heading_ratio: Optional[float] = None
    governance_drop_low_density: Optional[bool] = None
    governance_drop_low_density_threshold: Optional[float] = None
    governance_unwrap_max_line_length: Optional[int] = None
    governance_noise_min_chars: Optional[int] = None
    governance_noise_ratio_threshold: Optional[float] = None
    governance_common_lines_min_docs: Optional[int] = None
    governance_common_lines_min_ratio: Optional[float] = None
    parse_fallback_enabled: Optional[bool] = None
    parse_fallback_min_content_chars: Optional[int] = None
    parse_fallback_max_retries: Optional[int] = None
    persist_parsed_content: Optional[bool] = None
    persist_parsed_content_max_chars: Optional[int] = None
    near_dedup_enabled: Optional[bool] = None
    near_dedup_hamming_threshold: Optional[int] = None
    near_dedup_max_bucket_size: Optional[int] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    chunk_vector_enabled: Optional[bool] = None
    bm25_index_enabled: Optional[bool] = None
    kg_enabled: Optional[bool] = None
    event_vector_enabled: Optional[bool] = None
    entity_vector_enabled: Optional[bool] = None


@dataclass(frozen=True)
class PipelineEffective:
    governance_enabled: bool
    governance_remove_toc_lines: bool
    governance_remove_noise_lines: bool
    governance_unwrap_lines: bool
    governance_remove_common_lines: bool
    governance_remove_boilerplate: bool
    governance_remove_images: str
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
    governance_secrets_redact: bool
    governance_secrets_mode: str
    governance_secrets_mask: str
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
    parse_fallback_max_retries: int
    persist_parsed_content: bool
    persist_parsed_content_max_chars: int
    near_dedup_enabled: bool
    near_dedup_hamming_threshold: int
    near_dedup_max_bucket_size: int
    chunk_size: int
    chunk_overlap: int
    chunk_vector_enabled: bool
    bm25_index_enabled: bool
    kg_enabled: bool
    event_vector_enabled: bool
    entity_vector_enabled: bool


__all__ = [
    "PipelineEffective",
    "PipelineOptions",
]
