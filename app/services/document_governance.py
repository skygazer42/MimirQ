"""Translate effective pipeline settings into shared document governance options."""

from app.rag.preprocessing.processor import GovernanceCleanOptions
from app.types.pipeline import PipelineEffective


def build_governance_options(
    pipeline_effective: PipelineEffective,
    *,
    remove_common_lines: bool | None = None,
) -> GovernanceCleanOptions:
    """Build common options; ingestion applies its aggregate hit limits separately."""
    return GovernanceCleanOptions(
        remove_toc_lines=pipeline_effective.governance_remove_toc_lines,
        remove_noise_lines=pipeline_effective.governance_remove_noise_lines,
        unwrap_lines=pipeline_effective.governance_unwrap_lines,
        remove_common_lines=(
            pipeline_effective.governance_remove_common_lines if remove_common_lines is None else remove_common_lines
        ),
        remove_boilerplate=pipeline_effective.governance_remove_boilerplate,
        remove_images=pipeline_effective.governance_remove_images,
        extract_frontmatter=pipeline_effective.governance_extract_frontmatter,
        strip_frontmatter=pipeline_effective.governance_strip_frontmatter,
        detect_language=pipeline_effective.governance_detect_language,
        language_min_chars=pipeline_effective.governance_language_min_chars,
        normalize_urls=pipeline_effective.governance_normalize_urls,
        normalize_urls_strip_tracking=pipeline_effective.governance_normalize_urls_strip_tracking,
        drop_duplicate_paragraphs=pipeline_effective.governance_drop_duplicate_paragraphs,
        drop_duplicate_paragraphs_min_occurrences=(
            pipeline_effective.governance_drop_duplicate_paragraphs_min_occurrences
        ),
        drop_duplicate_paragraphs_min_chars=pipeline_effective.governance_drop_duplicate_paragraphs_min_chars,
        drop_duplicate_paragraphs_max_chars=pipeline_effective.governance_drop_duplicate_paragraphs_max_chars,
        trim_references=pipeline_effective.governance_trim_references,
        extract_keywords=pipeline_effective.governance_extract_keywords,
        keywords_provider=pipeline_effective.governance_keywords_provider,
        keywords_top_k=pipeline_effective.governance_keywords_top_k,
        keywords_max_chars=pipeline_effective.governance_keywords_max_chars,
        normalize_tables=pipeline_effective.governance_normalize_tables,
        strip_code_line_numbers=pipeline_effective.governance_strip_code_line_numbers,
        pii_anonymize=pipeline_effective.governance_pii_anonymize,
        pii_mode=pipeline_effective.governance_pii_mode,
        pii_mask=pipeline_effective.governance_pii_mask,
        secrets_redact=pipeline_effective.governance_secrets_redact,
        secrets_mode=pipeline_effective.governance_secrets_mode,
        secrets_mask=pipeline_effective.governance_secrets_mask,
        max_blank_lines=pipeline_effective.governance_max_blank_lines,
        drop_outline_only=pipeline_effective.governance_drop_outline_only,
        drop_outline_min_content_chars=pipeline_effective.governance_drop_outline_min_content_chars,
        drop_outline_max_heading_ratio=pipeline_effective.governance_drop_outline_max_heading_ratio,
        drop_low_density=pipeline_effective.governance_drop_low_density,
        drop_low_density_threshold=pipeline_effective.governance_drop_low_density_threshold,
        unwrap_max_line_length=pipeline_effective.governance_unwrap_max_line_length,
        noise_min_chars=pipeline_effective.governance_noise_min_chars,
        noise_ratio_threshold=pipeline_effective.governance_noise_ratio_threshold,
        common_lines_min_docs=pipeline_effective.governance_common_lines_min_docs,
        common_lines_min_ratio=pipeline_effective.governance_common_lines_min_ratio,
    )
