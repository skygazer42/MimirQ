"""Configuration and results of post-parse document governance."""

from dataclasses import dataclass, field
from typing import Literal

GOVERNANCE_RULESET_VERSION = "1"


@dataclass(frozen=True)
class GovernanceStats:
    documents: int
    changed: int
    applied_rules: int
    version: str = GOVERNANCE_RULESET_VERSION
    dropped: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    pii_hits: dict[str, int] = field(default_factory=dict)
    secrets_hits: dict[str, int] = field(default_factory=dict)
    frontmatter_docs: int = 0
    frontmatter_stripped_docs: int = 0
    paragraphs_dropped: int = 0
    references_removed_lines: int = 0
    urls_changed: int = 0
    boilerplate_removed_sections: int = 0
    boilerplate_removed_lines: int = 0
    images_removed: int = 0
    tables_normalized: int = 0
    table_rows_changed: int = 0
    code_blocks_changed: int = 0
    code_lines_stripped: int = 0
    keywords_docs: int = 0
    keywords_total: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    titles_docs: int = 0
    tags_docs: int = 0


@dataclass(frozen=True)
class GovernanceCleanOptions:
    extract_frontmatter: bool = False
    strip_frontmatter: bool = False
    detect_language: bool = False
    language_min_chars: int = 40
    normalize_urls: bool = False
    normalize_urls_strip_tracking: bool = True
    drop_duplicate_paragraphs: bool = False
    drop_duplicate_paragraphs_min_occurrences: int = 3
    drop_duplicate_paragraphs_min_chars: int = 40
    drop_duplicate_paragraphs_max_chars: int = 1200
    trim_references: bool = False
    extract_keywords: bool = False
    keywords_provider: str = "auto"
    keywords_top_k: int = 10
    keywords_max_chars: int = 20_000
    remove_toc_lines: bool = True
    remove_noise_lines: bool = True
    unwrap_lines: bool = True
    remove_common_lines: bool = True
    remove_boilerplate: bool = False
    remove_images: Literal["none", "decorative", "all"] = "none"
    normalize_tables: bool = False
    strip_code_line_numbers: bool = False
    pii_anonymize: bool = False
    pii_mode: Literal["mask", "token"] = "mask"
    pii_mask: str = "[REDACTED]"
    pii_max_hits: int = -1
    secrets_redact: bool = False
    secrets_mode: Literal["mask", "token"] = "mask"
    secrets_mask: str = "[SECRET]"
    secrets_max_hits: int = -1
    max_blank_lines: int = 1
    drop_outline_only: bool = False
    drop_outline_min_content_chars: int = 200
    drop_outline_max_heading_ratio: float = 0.85
    drop_low_density: bool = False
    drop_low_density_threshold: float = 0.12
    drop_high_perplexity: bool = False
    drop_high_perplexity_threshold: float = 0.55
    drop_high_perplexity_min_tokens: int = 20
    collapse_blank_lines: bool = True
    unwrap_max_line_length: int = 120
    noise_min_chars: int = 2
    noise_ratio_threshold: float = 0.2
    common_lines_min_docs: int = 3
    common_lines_min_ratio: float = 0.35
