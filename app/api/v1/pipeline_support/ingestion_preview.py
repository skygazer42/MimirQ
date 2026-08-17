"""Small ingestion-preview config/data helpers for the pipeline API.

Extracted verbatim from ``app/api/v1/pipeline.py``. Most ingestion-preview
helpers stay in ``app.api.v1.pipeline`` because tests monkeypatch them there.
Submodules must not import ``app.api.v1.pipeline`` (circular import).
"""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from app.api.schemas.pipeline import CleanPreviewRequest, CleanRegexRuleModel
from app.core.config import settings
from app.parsing.preprocess.file_preprocessor import preprocess_file

from .clean_preview import REDACTED_MASK, SECRET_MASK


@dataclass
class _IngestionPreviewConfig:
    base_parser_backend: str
    base_chunk_strategy: str
    parser_backend_choice: str
    chunk_strategy_choice: str
    preprocess_steps: list[dict[str, object]] = field(default_factory=list)
    governance_profile_ref: str | None = None
    patch_dict: dict[str, object] = field(default_factory=dict)


def _empty_preprocess_summary() -> dict[str, object]:
    return {"changed": False, "size_before": 0, "size_after": 0, "steps": [], "warnings": []}


def _ingestion_preview_defaults(
    parser_backend: str | None,
    chunk_strategy: str | None,
) -> tuple[str, str, str, str]:
    default_pb = (getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    default_cs = (
        (getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()
    )
    base_pb = (parser_backend or default_pb).strip().lower() or default_pb
    base_cs = (chunk_strategy or default_cs).strip().lower() or default_cs
    return default_pb, default_cs, base_pb, base_cs


def _ingestion_rule_preprocess_steps(matched_rule: object | None) -> list[dict[str, object]]:
    preprocess = getattr(matched_rule, "preprocess", None) if matched_rule is not None else None
    steps = (
        getattr(preprocess, "steps", None)
        if preprocess is not None and bool(getattr(preprocess, "enabled", True))
        else None
    )
    if not isinstance(steps, list) or not steps:
        return []
    return [
        {
            "id": str(getattr(step, "id", "") or "").strip(),
            "params": dict(getattr(step, "params", {}) or {}),
        }
        for step in steps
    ]


def _effective_bool(effective: object, name: str, default: bool) -> bool:
    return bool(getattr(effective, name, default))


def _effective_int(effective: object, name: str, default: int) -> int:
    return int(getattr(effective, name, default) or default)


def _effective_float(effective: object, name: str, default: float) -> float:
    return float(getattr(effective, name, default) or default)


def _effective_str(effective: object, name: str, default: str) -> str:
    return str(getattr(effective, name, default) or default)


def _dataset_metadata_dict(dataset: object) -> dict[str, object]:
    dataset_meta = getattr(dataset, "dataset_metadata", None)
    return dataset_meta if isinstance(dataset_meta, dict) else {}


def _preprocess_ingestion_preview_file(
    temp_path: Path,
    preprocess_steps: list[dict[str, object]],
) -> tuple[Path, dict[str, object]]:
    if not preprocess_steps:
        return temp_path, _empty_preprocess_summary()

    pre = preprocess_file(input_path=temp_path, steps=preprocess_steps)
    summary = {
        "changed": bool(pre.changed),
        "size_before": int(pre.size_before),
        "size_after": int(pre.size_after),
        "steps": [
            {
                "id": step.id,
                "applied": bool(step.applied),
                "changed": bool(step.changed),
                "note": step.note,
                "bytes_before": int(getattr(step, "bytes_before", 0) or 0),
                "bytes_after": int(getattr(step, "bytes_after", 0) or 0),
                "elapsed_ms": int(getattr(step, "elapsed_ms", 0) or 0),
            }
            for step in (pre.steps or [])
        ],
        "warnings": list(pre.warnings or []),
    }
    parse_path = Path(str(pre.output_path)) if bool(pre.changed) else temp_path
    return parse_path, summary


def _build_ingestion_clean_preview_request(
    *,
    parsed: dict[str, object],
    effective: object,
    diff_max_lines: int,
) -> CleanPreviewRequest:
    return CleanPreviewRequest(
        markdown=str(parsed.get("markdown") or ""),
        rules=[CleanRegexRuleModel(**rule) for rule in (getattr(effective, "governance_regex_rules", None) or [])],
        use_default_rules=True,
        include_diff=True,
        diff_max_lines=int(diff_max_lines or 0),
        input_format="markdown",
        html_xpath=None,
        normalize_line_endings=True,
        trim_trailing_spaces=True,
        collapse_blank_lines=True,
        max_blank_lines=_effective_int(effective, "governance_max_blank_lines", 1),
        remove_control_chars=True,
        remove_toc_lines=_effective_bool(effective, "governance_remove_toc_lines", True),
        remove_noise_lines=_effective_bool(effective, "governance_remove_noise_lines", True),
        remove_common_lines=_effective_bool(effective, "governance_remove_common_lines", True),
        unwrap_lines=_effective_bool(effective, "governance_unwrap_lines", True),
        remove_boilerplate=_effective_bool(effective, "governance_remove_boilerplate", False),
        remove_images=_effective_str(effective, "governance_remove_images", "none"),  # type: ignore[arg-type]
        extract_frontmatter=_effective_bool(effective, "governance_extract_frontmatter", False),
        strip_frontmatter=_effective_bool(effective, "governance_strip_frontmatter", False),
        detect_language=_effective_bool(effective, "governance_detect_language", False),
        language_min_chars=_effective_int(effective, "governance_language_min_chars", 40),
        normalize_urls=_effective_bool(effective, "governance_normalize_urls", False),
        normalize_urls_strip_tracking=_effective_bool(effective, "governance_normalize_urls_strip_tracking", True),
        drop_duplicate_paragraphs=_effective_bool(effective, "governance_drop_duplicate_paragraphs", False),
        drop_duplicate_paragraphs_min_occurrences=_effective_int(
            effective,
            "governance_drop_duplicate_paragraphs_min_occurrences",
            3,
        ),
        drop_duplicate_paragraphs_min_chars=_effective_int(
            effective,
            "governance_drop_duplicate_paragraphs_min_chars",
            40,
        ),
        drop_duplicate_paragraphs_max_chars=_effective_int(
            effective,
            "governance_drop_duplicate_paragraphs_max_chars",
            1200,
        ),
        trim_references=_effective_bool(effective, "governance_trim_references", False),
        extract_keywords=_effective_bool(effective, "governance_extract_keywords", False),
        keywords_provider=_effective_str(effective, "governance_keywords_provider", "auto"),
        keywords_top_k=_effective_int(effective, "governance_keywords_top_k", 10),
        keywords_max_chars=_effective_int(effective, "governance_keywords_max_chars", 20000),
        normalize_tables=_effective_bool(effective, "governance_normalize_tables", False),
        strip_code_line_numbers=_effective_bool(effective, "governance_strip_code_line_numbers", False),
        pii_anonymize=_effective_bool(effective, "governance_pii_anonymize", False),
        pii_mode=_effective_str(effective, "governance_pii_mode", "mask"),  # type: ignore[arg-type]
        pii_mask=_effective_str(effective, "governance_pii_mask", REDACTED_MASK),
        secrets_redact=_effective_bool(effective, "governance_secrets_redact", False),
        secrets_mode=_effective_str(effective, "governance_secrets_mode", "mask"),  # type: ignore[arg-type]
        secrets_mask=_effective_str(effective, "governance_secrets_mask", SECRET_MASK),
        drop_outline_only=_effective_bool(effective, "governance_drop_outline_only", False),
        drop_outline_min_content_chars=_effective_int(effective, "governance_drop_outline_min_content_chars", 200),
        drop_outline_max_heading_ratio=_effective_float(effective, "governance_drop_outline_max_heading_ratio", 0.85),
        drop_low_density=_effective_bool(effective, "governance_drop_low_density", False),
        drop_low_density_threshold=_effective_float(effective, "governance_drop_low_density_threshold", 0.12),
        unwrap_max_line_length=_effective_int(effective, "governance_unwrap_max_line_length", 120),
        noise_min_chars=_effective_int(effective, "governance_noise_min_chars", 2),
        noise_ratio_threshold=_effective_float(effective, "governance_noise_ratio_threshold", 0.2),
        common_lines_min_occurrences=_effective_int(effective, "governance_common_lines_min_docs", 3),
    )


def _ingestion_preview_rule_output(
    matched_rule: object | None,
    config: _IngestionPreviewConfig,
) -> dict[str, object]:
    return {
        "matched": matched_rule is not None,
        "rule_id": getattr(matched_rule, "id", None) if matched_rule is not None else None,
        "rule_name": getattr(matched_rule, "name", None) if matched_rule is not None else None,
        "governance_profile_ref": config.governance_profile_ref,
        "preprocess_steps": config.preprocess_steps,
        "parser_backend": str(config.parser_backend_choice or "auto"),
        "chunk_strategy": str(config.chunk_strategy_choice or ""),
    }


def _ingestion_preview_explain(
    *,
    dataset_id: UUID,
    file: object,
    file_ext: str,
    config: _IngestionPreviewConfig,
    rule_out: dict[str, object],
    pre_summary: dict[str, object],
    parsed: dict[str, object],
) -> dict[str, object]:
    filename = str(getattr(file, "filename", "") or "")
    return {
        "dataset_id": str(dataset_id),
        "filename": filename,
        "file_type": str(file_ext or ""),
        "requested": {
            "parser_backend": str(config.base_parser_backend or ""),
            "chunk_strategy": str(config.base_chunk_strategy or ""),
        },
        "rule": rule_out,
        "snapshot": {
            "dataset_id": str(dataset_id),
            "filename": filename,
            "file_type": str(file_ext or ""),
            "rule": rule_out,
            "preprocess": dict(pre_summary),
            "pipeline_patch": dict(config.patch_dict),
            "parser_backend": str(config.parser_backend_choice or "auto"),
            "chunk_strategy": str(config.chunk_strategy_choice or ""),
            "parse_backend": str(parsed.get("backend") or ""),
            "pdf_quality": parsed.get("pdf_quality"),
        },
    }
