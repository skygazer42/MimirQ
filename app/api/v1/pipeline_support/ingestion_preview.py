"""Build ingestion previews from the matched policy and resolved pipeline."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from app.api.schemas.pipelines import CleanPreviewRequest, CleanRegexRuleModel
from app.api.schemas.sources import IngestionRule
from app.core.config import settings
from app.parsing.preprocess.file_preprocessor import preprocess_file
from app.types.pipeline import PipelineEffective


@dataclass
class _IngestionPreviewConfig:
    base_parser_backend: str
    base_chunk_strategy: str
    parser_backend_choice: str
    chunk_strategy_choice: str
    preprocess_steps: list[dict[str, object]] = field(default_factory=list)
    governance_profile_ref: str | None = None
    patch_dict: dict[str, object] = field(default_factory=dict)


def _ingestion_preview_defaults(
    parser_backend: str | None,
    chunk_strategy: str | None,
) -> tuple[str, str, str, str]:
    default_parser_backend = settings.DEFAULT_PARSER_BACKEND.strip().lower()
    default_chunk_strategy = settings.DEFAULT_CHUNK_STRATEGY.strip().lower()
    base_parser_backend = default_parser_backend
    base_chunk_strategy = default_chunk_strategy
    if parser_backend and parser_backend.strip():
        base_parser_backend = parser_backend.strip().lower()
    if chunk_strategy and chunk_strategy.strip():
        base_chunk_strategy = chunk_strategy.strip().lower()
    return default_parser_backend, default_chunk_strategy, base_parser_backend, base_chunk_strategy


def _ingestion_rule_preprocess_steps(matched_rule: IngestionRule | None) -> list[dict[str, object]]:
    if matched_rule is None or not matched_rule.preprocess.enabled:
        return []
    return [
        {
            "id": step.id.strip(),
            "params": dict(step.params),
        }
        for step in matched_rule.preprocess.steps
    ]


def _preprocess_ingestion_preview_file(
    temp_path: Path,
    preprocess_steps: list[dict[str, object]],
) -> tuple[Path, dict[str, object]]:
    if not preprocess_steps:
        return temp_path, {"changed": False, "size_before": 0, "size_after": 0, "steps": [], "warnings": []}

    pre = preprocess_file(input_path=temp_path, steps=preprocess_steps)
    summary = {
        "changed": pre.changed,
        "size_before": pre.size_before,
        "size_after": pre.size_after,
        "steps": [
            {
                "id": step.id,
                "applied": step.applied,
                "changed": step.changed,
                "note": step.note,
                "bytes_before": step.bytes_before,
                "bytes_after": step.bytes_after,
                "elapsed_ms": step.elapsed_ms,
            }
            for step in pre.steps
        ],
        "warnings": list(pre.warnings),
    }
    parse_path = Path(pre.output_path) if pre.changed else temp_path
    return parse_path, summary


def _build_ingestion_clean_preview_request(
    *,
    markdown: str,
    effective: PipelineEffective,
    diff_max_lines: int,
) -> CleanPreviewRequest:
    return CleanPreviewRequest(
        markdown=markdown,
        rules=[CleanRegexRuleModel(**rule) for rule in effective.governance_regex_rules],
        include_diff=True,
        diff_max_lines=diff_max_lines,
        max_blank_lines=effective.governance_max_blank_lines,
        remove_toc_lines=effective.governance_remove_toc_lines,
        remove_noise_lines=effective.governance_remove_noise_lines,
        remove_common_lines=effective.governance_remove_common_lines,
        unwrap_lines=effective.governance_unwrap_lines,
        remove_boilerplate=effective.governance_remove_boilerplate,
        remove_images=effective.governance_remove_images,  # type: ignore[arg-type]
        extract_frontmatter=effective.governance_extract_frontmatter,
        strip_frontmatter=effective.governance_strip_frontmatter,
        detect_language=effective.governance_detect_language,
        language_min_chars=effective.governance_language_min_chars,
        normalize_urls=effective.governance_normalize_urls,
        normalize_urls_strip_tracking=effective.governance_normalize_urls_strip_tracking,
        drop_duplicate_paragraphs=effective.governance_drop_duplicate_paragraphs,
        drop_duplicate_paragraphs_min_occurrences=effective.governance_drop_duplicate_paragraphs_min_occurrences,
        drop_duplicate_paragraphs_min_chars=effective.governance_drop_duplicate_paragraphs_min_chars,
        drop_duplicate_paragraphs_max_chars=effective.governance_drop_duplicate_paragraphs_max_chars,
        trim_references=effective.governance_trim_references,
        extract_keywords=effective.governance_extract_keywords,
        keywords_provider=effective.governance_keywords_provider,
        keywords_top_k=effective.governance_keywords_top_k,
        keywords_max_chars=effective.governance_keywords_max_chars,
        normalize_tables=effective.governance_normalize_tables,
        strip_code_line_numbers=effective.governance_strip_code_line_numbers,
        pii_anonymize=effective.governance_pii_anonymize,
        pii_mode=effective.governance_pii_mode,  # type: ignore[arg-type]
        pii_mask=effective.governance_pii_mask,
        secrets_redact=effective.governance_secrets_redact,
        secrets_mode=effective.governance_secrets_mode,  # type: ignore[arg-type]
        secrets_mask=effective.governance_secrets_mask,
        drop_outline_only=effective.governance_drop_outline_only,
        drop_outline_min_content_chars=effective.governance_drop_outline_min_content_chars,
        drop_outline_max_heading_ratio=effective.governance_drop_outline_max_heading_ratio,
        drop_low_density=effective.governance_drop_low_density,
        drop_low_density_threshold=effective.governance_drop_low_density_threshold,
        unwrap_max_line_length=effective.governance_unwrap_max_line_length,
        noise_min_chars=effective.governance_noise_min_chars,
        noise_ratio_threshold=effective.governance_noise_ratio_threshold,
        common_lines_min_occurrences=effective.governance_common_lines_min_docs,
    )


def _ingestion_preview_rule_output(
    matched_rule: IngestionRule | None,
    config: _IngestionPreviewConfig,
) -> dict[str, object]:
    return {
        "matched": matched_rule is not None,
        "rule_id": matched_rule.id if matched_rule is not None else None,
        "rule_name": matched_rule.name if matched_rule is not None else None,
        "governance_profile_ref": config.governance_profile_ref,
        "preprocess_steps": config.preprocess_steps,
        "parser_backend": config.parser_backend_choice,
        "chunk_strategy": config.chunk_strategy_choice,
    }


def _ingestion_preview_explain(
    *,
    dataset_id: UUID,
    filename: str,
    file_ext: str,
    config: _IngestionPreviewConfig,
    rule_out: dict[str, object],
    pre_summary: dict[str, object],
    parsed: dict[str, object],
) -> dict[str, object]:
    return {
        "dataset_id": str(dataset_id),
        "filename": filename,
        "file_type": file_ext,
        "requested": {
            "parser_backend": config.base_parser_backend,
            "chunk_strategy": config.base_chunk_strategy,
        },
        "rule": rule_out,
        "snapshot": {
            "dataset_id": str(dataset_id),
            "filename": filename,
            "file_type": file_ext,
            "rule": rule_out,
            "preprocess": dict(pre_summary),
            "pipeline_patch": dict(config.patch_dict),
            "parser_backend": config.parser_backend_choice,
            "chunk_strategy": config.chunk_strategy_choice,
            "parse_backend": parsed["backend"],
            "pdf_quality": parsed.get("pdf_quality"),
        },
    }
