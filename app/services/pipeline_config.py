"""
Pipeline configuration service.

Provides parsing, building, and resolution for pipeline configuration.
"""

import re
from dataclasses import asdict
from typing import Any, Callable

from app.core.config import settings
from app.core.regex_safety import looks_like_nested_quantifier
from app.rag.core.logging import get_logger
from app.rag.pipeline_plugins.refs import sanitize_python_plugin_ref
from app.types.indexing import IndexingOptions
from app.types.pipeline import PipelineEffective, PipelineOptions

DEFAULT_GOVERNANCE_PII_MASK = "[REDACTED]"
DEFAULT_GOVERNANCE_SECRETS_MASK = "[SECRET]"
_PRE_POC_QUALITY_GATE_MODES = {"off", "warn", "strict"}


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None


def _normalize_pre_poc_quality_gate_mode(value: Any) -> str:
    mode = str(value or "warn").strip().lower()
    return mode if mode in _PRE_POC_QUALITY_GATE_MODES else "warn"


_ALLOWED_RE_FLAG_BITS = int(re.IGNORECASE | re.MULTILINE | re.DOTALL)
_REGEX_RULES_MAX = 60
_REGEX_PATTERN_MAX = 600
_REGEX_REPL_MAX = 2000
_RULE_PACKS_MAX = 20
_RULE_PACK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.:\-]{0,63}$")


def _sanitize_chunk_strategy_params(value: Any) -> dict[str, Any] | None:
    """
    Best-effort validation for user-provided chunk strategy params stored in metadata.

    Security: keep it declarative and small (primitive values only).
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        return None
    if len(value) > 30:
        return None

    cleaned: dict[str, Any] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            continue
        key = k.strip()
        if not key or len(key) > 80:
            continue
        if v is None or isinstance(v, (bool, int, float)):
            cleaned[key] = v
            continue
        if isinstance(v, str):
            if len(v) > 500:
                continue
            cleaned[key] = v
        # No nested objects/lists.

    return cleaned or None


def _sanitize_stage_python_plugin_ref(value: Any, expected_stage: str) -> str | None:
    return sanitize_python_plugin_ref(value, expected_stage=expected_stage)


def _sanitize_regex_pattern(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    pattern = value.strip()
    if not pattern or len(pattern) > _REGEX_PATTERN_MAX:
        return None
    if looks_like_nested_quantifier(pattern):
        return None
    return pattern


def _sanitize_regex_replacement(value: Any) -> str:
    if value is None:
        return ""
    repl = value if isinstance(value, str) else str(value)
    return repl[:_REGEX_REPL_MAX]


def _sanitize_regex_flags(value: Any) -> int | None:
    try:
        flags = int(value)
    except Exception:
        get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
        return None
    if flags < 0 or (flags & ~_ALLOWED_RE_FLAG_BITS):
        return None
    return flags


def _sanitize_regex_rule(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    pattern = _sanitize_regex_pattern(item.get("pattern"))
    if pattern is None:
        return None
    flags = _sanitize_regex_flags(item.get("flags", 0))
    if flags is None:
        return None
    try:
        re.compile(pattern, flags=flags)
    except re.error:
        return None
    return {
        "pattern": pattern,
        "repl": _sanitize_regex_replacement(item.get("repl", "")),
        "flags": flags,
    }


def _sanitize_regex_rules(value: Any) -> list[dict] | None:
    """
    Best-effort validation for user-provided regex rules stored in metadata.

    Security:
    - Reject nested quantifiers (common ReDoS footgun)
    - Restrict flags to IGNORECASE/MULTILINE/DOTALL
    - Cap rule count and pattern length
    """
    if value is None:
        return None
    if not isinstance(value, list):
        return None

    out: list[dict] = []
    for item in value:
        sanitized = _sanitize_regex_rule(item)
        if sanitized is None:
            continue
        out.append(sanitized)
        if len(out) >= _REGEX_RULES_MAX:
            break

    return out or None


def _sanitize_rule_packs(value: Any) -> list[str] | None:
    """
    Best-effort validation for user-provided governance rule packs.

    Rule packs are server-defined presets (purely declarative) that expand to regex rules.
    Security/compatibility:
    - Keep the payload small and string-only
    - Normalize to lowercase for stable dedupe
    """
    if value is None:
        return None
    if not isinstance(value, list):
        return None

    out: list[str] = []
    seen: set[str] = set()

    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip().lower()
        if not name:
            continue
        if not _RULE_PACK_NAME_RE.match(name):
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= _RULE_PACKS_MAX:
            break

    return out or None


def _resolve_flag(default: bool, override: bool | None) -> bool:
    return bool(default) and override is not False


_MetadataTransform = Callable[[Any], Any]
_MetadataFieldSpec = tuple[str, str, _MetadataTransform]

_PIPELINE_METADATA_FIELDS: tuple[_MetadataFieldSpec, ...] = (
    ("governance_enabled", "governance_enabled", bool),
    ("parse_fallback_enabled", "parse_fallback_enabled", bool),
    ("parse_fallback_min_content_chars", "parse_fallback_min_content_chars", int),
    ("parse_fallback_min_parse_score", "parse_fallback_min_parse_score", float),
    ("parse_fallback_max_retries", "parse_fallback_max_retries", int),
    ("cross_page_merge_enabled", "cross_page_merge_enabled", bool),
    ("cross_page_merge_max_page_gap", "cross_page_merge_max_page_gap", int),
    ("reading_order_enabled", "reading_order_enabled", bool),
    ("parse_cache_enabled", "parse_cache_enabled", bool),
    ("parse_cache_ttl_sec", "parse_cache_ttl_sec", int),
    ("vlm_correction_enabled", "vlm_correction_enabled", bool),
    ("vlm_correction_min_table_score", "vlm_correction_min_table_score", float),
    ("vlm_correction_max_pages", "vlm_correction_max_pages", int),
    ("persist_parsed_content", "persist_parsed_content", bool),
    ("persist_parsed_content_max_chars", "persist_parsed_content_max_chars", int),
    ("chunk_size", "chunk_size", int),
    ("chunk_overlap", "chunk_overlap", int),
    ("chunk_merge_small_min_chars", "chunk_merge_small_min_chars", int),
)

_PIPELINE_METADATA_SANITIZED_FIELDS: tuple[_MetadataFieldSpec, ...] = (
    ("chunk_strategy_params", "chunk_strategy_params", _sanitize_chunk_strategy_params),
    ("chunk_python_plugin", "chunk_python_plugin", lambda value: _sanitize_stage_python_plugin_ref(value, "chunk")),
    ("chunk_python_params", "chunk_python_params", _sanitize_chunk_strategy_params),
    ("kg_python_plugin", "kg_python_plugin", lambda value: _sanitize_stage_python_plugin_ref(value, "kg")),
    ("kg_python_params", "kg_python_params", _sanitize_chunk_strategy_params),
)

_TABLES_METADATA_FIELDS: tuple[_MetadataFieldSpec, ...] = (
    ("table_store_enabled", "enabled", bool),
    ("table_store_max_rows", "max_rows", int),
    ("table_store_max_cols", "max_cols", int),
    ("table_store_sample_rows", "sample_rows", int),
    ("table_store_auto_route", "auto_route", bool),
    ("table_store_sidecar_exclusive_routing", "sidecar_exclusive_routing", bool),
    ("table_store_auto_row_threshold", "auto_row_threshold", int),
    ("table_store_auto_col_threshold", "auto_col_threshold", int),
    ("table_store_auto_sheet_threshold", "auto_sheet_threshold", int),
    ("table_store_auto_file_bytes_threshold", "auto_file_bytes_threshold", int),
)

_IMAGES_METADATA_FIELDS: tuple[_MetadataFieldSpec, ...] = (
    ("image_caption_enabled", "caption_enabled", bool),
    ("image_ocr_enabled", "ocr_enabled", bool),
    ("image_ocr_max_chars", "ocr_max_chars", int),
    ("image_ocr_max_images", "ocr_max_images", int),
)

_PRE_POC_METADATA_FIELDS: tuple[_MetadataFieldSpec, ...] = (
    ("ingest_pre_poc_scanner_enabled", "scanner_enabled", bool),
    ("ingest_pre_poc_quality_gate_mode", "quality_gate_mode", str),
)

_GOVERNANCE_METADATA_FIELDS: tuple[_MetadataFieldSpec, ...] = (
    ("governance_remove_toc_lines", "remove_toc_lines", bool),
    ("governance_remove_noise_lines", "remove_noise_lines", bool),
    ("governance_unwrap_lines", "unwrap_lines", bool),
    ("governance_remove_common_lines", "remove_common_lines", bool),
    ("governance_remove_boilerplate", "remove_boilerplate", bool),
    ("governance_remove_images", "remove_images", str),
    ("governance_extract_frontmatter", "extract_frontmatter", bool),
    ("governance_strip_frontmatter", "strip_frontmatter", bool),
    ("governance_detect_language", "detect_language", bool),
    ("governance_language_min_chars", "language_min_chars", int),
    ("governance_normalize_urls", "normalize_urls", bool),
    ("governance_normalize_urls_strip_tracking", "normalize_urls_strip_tracking", bool),
    ("governance_drop_duplicate_paragraphs", "drop_duplicate_paragraphs", bool),
    ("governance_drop_duplicate_paragraphs_min_occurrences", "drop_duplicate_paragraphs_min_occurrences", int),
    ("governance_drop_duplicate_paragraphs_min_chars", "drop_duplicate_paragraphs_min_chars", int),
    ("governance_drop_duplicate_paragraphs_max_chars", "drop_duplicate_paragraphs_max_chars", int),
    ("governance_trim_references", "trim_references", bool),
    ("governance_extract_keywords", "extract_keywords", bool),
    ("governance_keywords_provider", "keywords_provider", str),
    ("governance_keywords_top_k", "keywords_top_k", int),
    ("governance_keywords_max_chars", "keywords_max_chars", int),
    ("governance_normalize_tables", "normalize_tables", bool),
    ("governance_strip_code_line_numbers", "strip_code_line_numbers", bool),
    ("governance_quarantine_on_drop", "quarantine_on_drop", bool),
    ("governance_pii_anonymize", "pii_anonymize", bool),
    ("governance_pii_mode", "pii_mode", str),
    ("governance_pii_mask", "pii_mask", str),
    ("governance_pii_max_hits", "pii_max_hits", int),
    ("governance_llm_auto_tagging_enabled", "llm_auto_tagging_enabled", bool),
    ("governance_llm_auto_tagging_max_chars", "llm_auto_tagging_max_chars", int),
    ("governance_llm_auto_tagging_max_items", "llm_auto_tagging_max_items", int),
    ("governance_secrets_redact", "secrets_redact", bool),
    ("governance_secrets_mode", "secrets_mode", str),
    ("governance_secrets_mask", "secrets_mask", str),
    ("governance_secrets_max_hits", "secrets_max_hits", int),
    ("governance_max_blank_lines", "max_blank_lines", int),
    ("governance_html_xpath", "html_xpath", str),
    ("governance_drop_outline_only", "drop_outline_only", bool),
    ("governance_drop_outline_min_content_chars", "drop_outline_min_content_chars", int),
    ("governance_drop_outline_max_heading_ratio", "drop_outline_max_heading_ratio", float),
    ("governance_drop_low_density", "drop_low_density", bool),
    ("governance_drop_low_density_threshold", "drop_low_density_threshold", float),
    ("governance_unwrap_max_line_length", "unwrap_max_line_length", int),
    ("governance_noise_min_chars", "noise_min_chars", int),
    ("governance_noise_ratio_threshold", "noise_ratio_threshold", float),
    ("governance_common_lines_min_docs", "common_lines_min_docs", int),
    ("governance_common_lines_min_ratio", "common_lines_min_ratio", float),
)

_GOVERNANCE_METADATA_SANITIZED_FIELDS: tuple[_MetadataFieldSpec, ...] = (
    ("governance_rule_packs", "rule_packs", _sanitize_rule_packs),
    ("governance_regex_rules", "regex_rules", _sanitize_regex_rules),
    ("governance_python_plugin", "python_plugin", lambda value: _sanitize_stage_python_plugin_ref(value, "governance")),
    ("governance_python_params", "python_params", _sanitize_chunk_strategy_params),
)

_DEDUP_METADATA_FIELDS: tuple[_MetadataFieldSpec, ...] = (
    ("near_dedup_enabled", "enabled", bool),
    ("near_dedup_hamming_threshold", "hamming_threshold", int),
    ("near_dedup_max_bucket_size", "max_bucket_size", int),
)

_INDEX_METADATA_FIELDS: tuple[_MetadataFieldSpec, ...] = (
    ("chunk_vector_enabled", "chunk_vector_enabled", bool),
    ("bm25_index_enabled", "bm25_index_enabled", bool),
    ("kg_enabled", "kg_enabled", bool),
    ("event_vector_enabled", "event_vector_enabled", bool),
    ("entity_vector_enabled", "entity_vector_enabled", bool),
    ("embedding_context_prefix_enabled", "embedding_context_prefix_enabled", bool),
    ("embedding_contextual_retrieval_enabled", "embedding_contextual_retrieval_enabled", bool),
    ("embedding_contextual_retrieval_lazy_mode", "embedding_contextual_retrieval_lazy_mode", bool),
    ("embedding_field_aware_enabled", "embedding_field_aware_enabled", bool),
)


def _apply_metadata_fields(
    options: PipelineOptions,
    target: dict[str, Any],
    fields: tuple[_MetadataFieldSpec, ...],
) -> None:
    for attr_name, metadata_key, transform in fields:
        value = getattr(options, attr_name)
        if value is None:
            continue
        target[metadata_key] = transform(value)


def _apply_sanitized_metadata_fields(
    options: PipelineOptions,
    target: dict[str, Any],
    fields: tuple[_MetadataFieldSpec, ...],
) -> None:
    for attr_name, metadata_key, sanitize in fields:
        value = getattr(options, attr_name)
        if value is None:
            continue
        sanitized = sanitize(value)
        if sanitized:
            target[metadata_key] = sanitized


def _build_tables_metadata(options: PipelineOptions) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    _apply_metadata_fields(options, tables, _TABLES_METADATA_FIELDS)
    return tables


def _build_images_metadata(options: PipelineOptions) -> dict[str, Any]:
    images: dict[str, Any] = {}
    _apply_metadata_fields(options, images, _IMAGES_METADATA_FIELDS)
    return images


def _build_pre_poc_metadata(options: PipelineOptions) -> dict[str, Any]:
    pre_poc: dict[str, Any] = {}
    _apply_metadata_fields(options, pre_poc, _PRE_POC_METADATA_FIELDS)
    return pre_poc


def _build_governance_metadata(options: PipelineOptions) -> dict[str, Any]:
    governance: dict[str, Any] = {}
    _apply_metadata_fields(
        options,
        governance,
        _GOVERNANCE_METADATA_FIELDS[:6],
    )
    _apply_sanitized_metadata_fields(
        options,
        governance,
        _GOVERNANCE_METADATA_SANITIZED_FIELDS[:2],
    )
    _apply_metadata_fields(
        options,
        governance,
        _GOVERNANCE_METADATA_FIELDS[6:],
    )
    _apply_sanitized_metadata_fields(
        options,
        governance,
        _GOVERNANCE_METADATA_SANITIZED_FIELDS[2:],
    )
    return governance


def _build_dedup_metadata(options: PipelineOptions) -> dict[str, Any]:
    dedup: dict[str, Any] = {}
    _apply_metadata_fields(options, dedup, _DEDUP_METADATA_FIELDS)
    return dedup


def _build_index_metadata(options: PipelineOptions) -> dict[str, Any]:
    index: dict[str, Any] = {}
    _apply_metadata_fields(options, index, _INDEX_METADATA_FIELDS)
    return index


def merge_pipeline_options(*options: PipelineOptions) -> PipelineOptions:
    """
    Merge PipelineOptions with "last non-None wins" semantics.

    This is the core primitive for tenant->dataset->document->request override merges.
    """
    merged: dict[str, Any] = {}
    for opt in options:
        if opt is None:
            continue
        data = asdict(opt)
        for k, v in data.items():
            if v is not None:
                merged[k] = v
    return PipelineOptions(**merged) if merged else PipelineOptions()


def parse_pipeline_from_metadata(metadata: dict[str, Any]) -> PipelineOptions:
    if not isinstance(metadata, dict):
        return PipelineOptions()
    pipeline = metadata.get("pipeline")
    if not isinstance(pipeline, dict):
        return PipelineOptions()

    index = pipeline.get("index")
    if not isinstance(index, dict):
        index = {}
    tables = pipeline.get("tables")
    if not isinstance(tables, dict):
        tables = {}
    images = pipeline.get("images")
    if not isinstance(images, dict):
        images = {}
    governance = pipeline.get("governance")
    if not isinstance(governance, dict):
        governance = {}
    pre_poc = pipeline.get("pre_poc")
    if not isinstance(pre_poc, dict):
        pre_poc = {}
    dedup = pipeline.get("dedup")
    if not isinstance(dedup, dict):
        dedup = {}

    return PipelineOptions(
        governance_enabled=_coerce_bool(pipeline.get("governance_enabled")),
        governance_remove_toc_lines=_coerce_bool(governance.get("remove_toc_lines")),
        governance_remove_noise_lines=_coerce_bool(governance.get("remove_noise_lines")),
        governance_unwrap_lines=_coerce_bool(governance.get("unwrap_lines")),
        governance_remove_common_lines=_coerce_bool(governance.get("remove_common_lines")),
        governance_remove_boilerplate=_coerce_bool(governance.get("remove_boilerplate")),
        governance_remove_images=_coerce_str(governance.get("remove_images")),
        governance_rule_packs=_sanitize_rule_packs(governance.get("rule_packs")),
        governance_regex_rules=_sanitize_regex_rules(governance.get("regex_rules")),
        governance_extract_frontmatter=_coerce_bool(governance.get("extract_frontmatter")),
        governance_strip_frontmatter=_coerce_bool(governance.get("strip_frontmatter")),
        governance_detect_language=_coerce_bool(governance.get("detect_language")),
        governance_language_min_chars=_coerce_int(governance.get("language_min_chars")),
        governance_normalize_urls=_coerce_bool(governance.get("normalize_urls")),
        governance_normalize_urls_strip_tracking=_coerce_bool(governance.get("normalize_urls_strip_tracking")),
        governance_drop_duplicate_paragraphs=_coerce_bool(governance.get("drop_duplicate_paragraphs")),
        governance_drop_duplicate_paragraphs_min_occurrences=_coerce_int(governance.get("drop_duplicate_paragraphs_min_occurrences")),
        governance_drop_duplicate_paragraphs_min_chars=_coerce_int(governance.get("drop_duplicate_paragraphs_min_chars")),
        governance_drop_duplicate_paragraphs_max_chars=_coerce_int(governance.get("drop_duplicate_paragraphs_max_chars")),
        governance_trim_references=_coerce_bool(governance.get("trim_references")),
        governance_extract_keywords=_coerce_bool(governance.get("extract_keywords")),
        governance_keywords_provider=_coerce_str(governance.get("keywords_provider")),
        governance_keywords_top_k=_coerce_int(governance.get("keywords_top_k")),
        governance_keywords_max_chars=_coerce_int(governance.get("keywords_max_chars")),
        governance_normalize_tables=_coerce_bool(governance.get("normalize_tables")),
        governance_strip_code_line_numbers=_coerce_bool(governance.get("strip_code_line_numbers")),
        governance_quarantine_on_drop=_coerce_bool(governance.get("quarantine_on_drop")),
        governance_pii_anonymize=_coerce_bool(governance.get("pii_anonymize")),
        governance_pii_mode=_coerce_str(governance.get("pii_mode")),
        governance_pii_mask=_coerce_str(governance.get("pii_mask")),
        governance_pii_max_hits=_coerce_int(governance.get("pii_max_hits")),
        governance_llm_auto_tagging_enabled=_coerce_bool(governance.get("llm_auto_tagging_enabled")),
        governance_llm_auto_tagging_max_chars=_coerce_int(governance.get("llm_auto_tagging_max_chars")),
        governance_llm_auto_tagging_max_items=_coerce_int(governance.get("llm_auto_tagging_max_items")),
        ingest_pre_poc_scanner_enabled=_coerce_bool(pre_poc.get("scanner_enabled")),
        ingest_pre_poc_quality_gate_mode=_coerce_str(pre_poc.get("quality_gate_mode")),
        governance_secrets_redact=_coerce_bool(governance.get("secrets_redact")),
        governance_secrets_mode=_coerce_str(governance.get("secrets_mode")),
        governance_secrets_mask=_coerce_str(governance.get("secrets_mask")),
        governance_secrets_max_hits=_coerce_int(governance.get("secrets_max_hits")),
        governance_max_blank_lines=_coerce_int(governance.get("max_blank_lines")),
        governance_html_xpath=_coerce_str(governance.get("html_xpath")),
        governance_drop_outline_only=_coerce_bool(governance.get("drop_outline_only")),
        governance_drop_outline_min_content_chars=_coerce_int(governance.get("drop_outline_min_content_chars")),
        governance_drop_outline_max_heading_ratio=_coerce_float(governance.get("drop_outline_max_heading_ratio")),
        governance_drop_low_density=_coerce_bool(governance.get("drop_low_density")),
        governance_drop_low_density_threshold=_coerce_float(governance.get("drop_low_density_threshold")),
        governance_unwrap_max_line_length=_coerce_int(governance.get("unwrap_max_line_length")),
        governance_noise_min_chars=_coerce_int(governance.get("noise_min_chars")),
        governance_noise_ratio_threshold=_coerce_float(governance.get("noise_ratio_threshold")),
        governance_common_lines_min_docs=_coerce_int(governance.get("common_lines_min_docs")),
        governance_common_lines_min_ratio=_coerce_float(governance.get("common_lines_min_ratio")),
        governance_python_plugin=_sanitize_stage_python_plugin_ref(governance.get("python_plugin"), "governance"),
        governance_python_params=_sanitize_chunk_strategy_params(governance.get("python_params")),
        parse_fallback_enabled=_coerce_bool(pipeline.get("parse_fallback_enabled")),
        parse_fallback_min_content_chars=_coerce_int(pipeline.get("parse_fallback_min_content_chars")),
        parse_fallback_min_parse_score=_coerce_float(pipeline.get("parse_fallback_min_parse_score")),
        parse_fallback_max_retries=_coerce_int(pipeline.get("parse_fallback_max_retries")),
        cross_page_merge_enabled=_coerce_bool(pipeline.get("cross_page_merge_enabled")),
        cross_page_merge_max_page_gap=_coerce_int(pipeline.get("cross_page_merge_max_page_gap")),
        reading_order_enabled=_coerce_bool(pipeline.get("reading_order_enabled")),
        parse_cache_enabled=_coerce_bool(pipeline.get("parse_cache_enabled")),
        parse_cache_ttl_sec=_coerce_int(pipeline.get("parse_cache_ttl_sec")),
        vlm_correction_enabled=_coerce_bool(pipeline.get("vlm_correction_enabled")),
        vlm_correction_min_table_score=_coerce_float(pipeline.get("vlm_correction_min_table_score")),
        vlm_correction_max_pages=_coerce_int(pipeline.get("vlm_correction_max_pages")),
        persist_parsed_content=_coerce_bool(pipeline.get("persist_parsed_content")),
        persist_parsed_content_max_chars=_coerce_int(pipeline.get("persist_parsed_content_max_chars")),
        near_dedup_enabled=_coerce_bool(dedup.get("enabled")),
        near_dedup_hamming_threshold=_coerce_int(dedup.get("hamming_threshold")),
        near_dedup_max_bucket_size=_coerce_int(dedup.get("max_bucket_size")),
        chunk_size=_coerce_int(pipeline.get("chunk_size")),
        chunk_overlap=_coerce_int(pipeline.get("chunk_overlap")),
        chunk_merge_small_min_chars=_coerce_int(pipeline.get("chunk_merge_small_min_chars")),
        chunk_strategy_params=_sanitize_chunk_strategy_params(pipeline.get("chunk_strategy_params")),
        chunk_python_plugin=_sanitize_stage_python_plugin_ref(pipeline.get("chunk_python_plugin"), "chunk"),
        chunk_python_params=_sanitize_chunk_strategy_params(pipeline.get("chunk_python_params")),
        embedding_context_prefix_enabled=_coerce_bool(index.get("embedding_context_prefix_enabled")),
        embedding_contextual_retrieval_enabled=_coerce_bool(index.get("embedding_contextual_retrieval_enabled")),
        embedding_contextual_retrieval_lazy_mode=_coerce_bool(index.get("embedding_contextual_retrieval_lazy_mode")),
        embedding_field_aware_enabled=_coerce_bool(index.get("embedding_field_aware_enabled")),
        chunk_vector_enabled=_coerce_bool(index.get("chunk_vector_enabled")),
        bm25_index_enabled=_coerce_bool(index.get("bm25_index_enabled")),
        kg_enabled=_coerce_bool(index.get("kg_enabled")),
        kg_python_plugin=_sanitize_stage_python_plugin_ref(pipeline.get("kg_python_plugin"), "kg"),
        kg_python_params=_sanitize_chunk_strategy_params(pipeline.get("kg_python_params")),
        event_vector_enabled=_coerce_bool(index.get("event_vector_enabled")),
        entity_vector_enabled=_coerce_bool(index.get("entity_vector_enabled")),
        table_store_enabled=_coerce_bool(tables.get("enabled")),
        table_store_max_rows=_coerce_int(tables.get("max_rows")),
        table_store_max_cols=_coerce_int(tables.get("max_cols")),
        table_store_sample_rows=_coerce_int(tables.get("sample_rows")),
        table_store_auto_route=_coerce_bool(tables.get("auto_route")),
        table_store_sidecar_exclusive_routing=_coerce_bool(tables.get("sidecar_exclusive_routing")),
        table_store_auto_row_threshold=_coerce_int(tables.get("auto_row_threshold")),
        table_store_auto_col_threshold=_coerce_int(tables.get("auto_col_threshold")),
        table_store_auto_sheet_threshold=_coerce_int(tables.get("auto_sheet_threshold")),
        table_store_auto_file_bytes_threshold=_coerce_int(tables.get("auto_file_bytes_threshold")),
        image_caption_enabled=_coerce_bool(images.get("caption_enabled")),
        image_ocr_enabled=_coerce_bool(images.get("ocr_enabled")),
        image_ocr_max_chars=_coerce_int(images.get("ocr_max_chars")),
        image_ocr_max_images=_coerce_int(images.get("ocr_max_images")),
    )


def build_pipeline_metadata(options: PipelineOptions) -> dict[str, Any] | None:
    if options is None:
        return None

    pipeline: dict[str, Any] = {}
    _apply_metadata_fields(options, pipeline, _PIPELINE_METADATA_FIELDS)
    _apply_sanitized_metadata_fields(options, pipeline, _PIPELINE_METADATA_SANITIZED_FIELDS)

    tables = _build_tables_metadata(options)
    if tables:
        pipeline["tables"] = tables

    images = _build_images_metadata(options)
    if images:
        pipeline["images"] = images

    pre_poc = _build_pre_poc_metadata(options)
    if pre_poc:
        pipeline["pre_poc"] = pre_poc

    governance = _build_governance_metadata(options)
    if governance:
        pipeline["governance"] = governance

    dedup = _build_dedup_metadata(options)
    if dedup:
        pipeline["dedup"] = dedup

    index = _build_index_metadata(options)
    if index:
        pipeline["index"] = index

    return pipeline or None


def upsert_pipeline_metadata(meta: dict[str, Any], *, options: PipelineOptions | None) -> bool:
    """
    Upsert `meta["pipeline"]` from PipelineOptions (or remove it when empty).

    Returns True when a change was applied to the dict.
    """
    if options is None:
        return False
    pipeline_meta = build_pipeline_metadata(options)
    if pipeline_meta:
        meta["pipeline"] = pipeline_meta
    else:
        meta.pop("pipeline", None)
    return True


def resolve_pipeline_effective(
    *,
    dataset_metadata: dict[str, Any] | None = None,
    document_metadata: dict[str, Any] | None = None,
    request_overrides: PipelineOptions | None = None,
) -> PipelineEffective:
    """
    Resolve the final PipelineEffective for a document processing path using 3 layers:

    Priority (later wins):
    - tenant defaults (settings)  [handled inside resolve_pipeline_options via None]
    - dataset metadata.pipeline
    - document metadata.pipeline
    - request_overrides (e.g., upload/preview payload)
    """
    dataset_opts = parse_pipeline_from_metadata(dataset_metadata or {}) if dataset_metadata else PipelineOptions()
    doc_opts = parse_pipeline_from_metadata(document_metadata or {}) if document_metadata else PipelineOptions()
    merged = merge_pipeline_options(dataset_opts, doc_opts, request_overrides or PipelineOptions())
    return resolve_pipeline_options(merged)


def resolve_pipeline_options(options: PipelineOptions) -> PipelineEffective:
    governance_enabled = (
        settings.GOVERNANCE_ENABLED
        if options.governance_enabled is None
        else bool(options.governance_enabled)
    )
    governance_remove_toc_lines = (
        settings.GOVERNANCE_REMOVE_TOC_LINES
        if options.governance_remove_toc_lines is None
        else bool(options.governance_remove_toc_lines)
    )
    governance_remove_noise_lines = (
        settings.GOVERNANCE_REMOVE_NOISE_LINES
        if options.governance_remove_noise_lines is None
        else bool(options.governance_remove_noise_lines)
    )
    governance_unwrap_lines = (
        settings.GOVERNANCE_UNWRAP_LINES
        if options.governance_unwrap_lines is None
        else bool(options.governance_unwrap_lines)
    )
    governance_remove_common_lines = (
        settings.GOVERNANCE_REMOVE_COMMON_LINES
        if options.governance_remove_common_lines is None
        else bool(options.governance_remove_common_lines)
    )
    governance_remove_boilerplate = (
        getattr(settings, "GOVERNANCE_REMOVE_BOILERPLATE", False)
        if options.governance_remove_boilerplate is None
        else bool(options.governance_remove_boilerplate)
    )
    governance_remove_images = (
        getattr(settings, "GOVERNANCE_REMOVE_IMAGES", "none")
        if options.governance_remove_images is None
        else str(options.governance_remove_images or "none")
    )
    governance_rule_packs = _sanitize_rule_packs(options.governance_rule_packs) or []
    governance_regex_rules = _sanitize_regex_rules(options.governance_regex_rules) or []
    governance_extract_frontmatter = (
        getattr(settings, "GOVERNANCE_EXTRACT_FRONTMATTER", False)
        if options.governance_extract_frontmatter is None
        else bool(options.governance_extract_frontmatter)
    )
    governance_strip_frontmatter = (
        getattr(settings, "GOVERNANCE_STRIP_FRONTMATTER", False)
        if options.governance_strip_frontmatter is None
        else bool(options.governance_strip_frontmatter)
    )
    governance_detect_language = (
        getattr(settings, "GOVERNANCE_DETECT_LANGUAGE", False)
        if options.governance_detect_language is None
        else bool(options.governance_detect_language)
    )
    governance_language_min_chars = (
        options.governance_language_min_chars
        if options.governance_language_min_chars is not None
        else int(getattr(settings, "GOVERNANCE_LANGUAGE_MIN_CHARS", 40) or 40)
    )
    governance_normalize_urls = (
        getattr(settings, "GOVERNANCE_NORMALIZE_URLS", False)
        if options.governance_normalize_urls is None
        else bool(options.governance_normalize_urls)
    )
    governance_normalize_urls_strip_tracking = (
        getattr(settings, "GOVERNANCE_NORMALIZE_URLS_STRIP_TRACKING", True)
        if options.governance_normalize_urls_strip_tracking is None
        else bool(options.governance_normalize_urls_strip_tracking)
    )
    governance_drop_duplicate_paragraphs = (
        getattr(settings, "GOVERNANCE_DROP_DUPLICATE_PARAGRAPHS", False)
        if options.governance_drop_duplicate_paragraphs is None
        else bool(options.governance_drop_duplicate_paragraphs)
    )
    governance_drop_duplicate_paragraphs_min_occurrences = (
        options.governance_drop_duplicate_paragraphs_min_occurrences
        if options.governance_drop_duplicate_paragraphs_min_occurrences is not None
        else int(getattr(settings, "GOVERNANCE_DROP_DUPLICATE_PARAGRAPHS_MIN_OCCURRENCES", 3) or 3)
    )
    governance_drop_duplicate_paragraphs_min_chars = (
        options.governance_drop_duplicate_paragraphs_min_chars
        if options.governance_drop_duplicate_paragraphs_min_chars is not None
        else int(getattr(settings, "GOVERNANCE_DROP_DUPLICATE_PARAGRAPHS_MIN_CHARS", 40) or 40)
    )
    governance_drop_duplicate_paragraphs_max_chars = (
        options.governance_drop_duplicate_paragraphs_max_chars
        if options.governance_drop_duplicate_paragraphs_max_chars is not None
        else int(getattr(settings, "GOVERNANCE_DROP_DUPLICATE_PARAGRAPHS_MAX_CHARS", 1200) or 1200)
    )
    governance_trim_references = (
        getattr(settings, "GOVERNANCE_TRIM_REFERENCES", False)
        if options.governance_trim_references is None
        else bool(options.governance_trim_references)
    )
    governance_extract_keywords = (
        getattr(settings, "GOVERNANCE_EXTRACT_KEYWORDS", False)
        if options.governance_extract_keywords is None
        else bool(options.governance_extract_keywords)
    )
    governance_keywords_provider = (
        getattr(settings, "GOVERNANCE_KEYWORDS_PROVIDER", "auto")
        if options.governance_keywords_provider is None
        else str(options.governance_keywords_provider or "auto")
    )
    governance_keywords_top_k = (
        options.governance_keywords_top_k
        if options.governance_keywords_top_k is not None
        else int(getattr(settings, "GOVERNANCE_KEYWORDS_TOP_K", 10) or 10)
    )
    governance_keywords_max_chars = (
        options.governance_keywords_max_chars
        if options.governance_keywords_max_chars is not None
        else int(getattr(settings, "GOVERNANCE_KEYWORDS_MAX_CHARS", 20_000) or 20_000)
    )
    governance_normalize_tables = (
        getattr(settings, "GOVERNANCE_NORMALIZE_TABLES", False)
        if options.governance_normalize_tables is None
        else bool(options.governance_normalize_tables)
    )
    governance_strip_code_line_numbers = (
        getattr(settings, "GOVERNANCE_STRIP_CODE_LINE_NUMBERS", False)
        if options.governance_strip_code_line_numbers is None
        else bool(options.governance_strip_code_line_numbers)
    )
    governance_quarantine_on_drop = (
        getattr(settings, "GOVERNANCE_QUARANTINE_ON_DROP", False)
        if options.governance_quarantine_on_drop is None
        else bool(options.governance_quarantine_on_drop)
    )
    governance_pii_anonymize = (
        getattr(settings, "GOVERNANCE_PII_ANONYMIZE", False)
        if options.governance_pii_anonymize is None
        else bool(options.governance_pii_anonymize)
    )
    governance_pii_mode = (
        getattr(settings, "GOVERNANCE_PII_MODE", "mask")
        if options.governance_pii_mode is None
        else str(options.governance_pii_mode or "mask")
    )
    governance_pii_mask = (
        getattr(settings, "GOVERNANCE_PII_MASK", DEFAULT_GOVERNANCE_PII_MASK)
        if options.governance_pii_mask is None
        else str(options.governance_pii_mask or DEFAULT_GOVERNANCE_PII_MASK)
    )
    governance_pii_max_hits = (
        options.governance_pii_max_hits
        if options.governance_pii_max_hits is not None
        else int(settings.GOVERNANCE_PII_MAX_HITS)
    )
    governance_llm_auto_tagging_enabled = (
        getattr(settings, "GOVERNANCE_LLM_AUTO_TAGGING_ENABLED", False)
        if options.governance_llm_auto_tagging_enabled is None
        else bool(options.governance_llm_auto_tagging_enabled)
    )
    governance_llm_auto_tagging_max_chars = (
        options.governance_llm_auto_tagging_max_chars
        if options.governance_llm_auto_tagging_max_chars is not None
        else int(getattr(settings, "GOVERNANCE_LLM_AUTO_TAGGING_MAX_CHARS", 3000) or 3000)
    )
    governance_llm_auto_tagging_max_items = (
        options.governance_llm_auto_tagging_max_items
        if options.governance_llm_auto_tagging_max_items is not None
        else int(getattr(settings, "GOVERNANCE_LLM_AUTO_TAGGING_MAX_ITEMS", 16) or 16)
    )
    ingest_pre_poc_scanner_enabled = (
        getattr(settings, "INGEST_PRE_POC_SCANNER_ENABLED", False)
        if options.ingest_pre_poc_scanner_enabled is None
        else bool(options.ingest_pre_poc_scanner_enabled)
    )
    ingest_pre_poc_quality_gate_mode = (
        getattr(settings, "INGEST_PRE_POC_QUALITY_GATE_MODE", "warn")
        if options.ingest_pre_poc_quality_gate_mode is None
        else str(options.ingest_pre_poc_quality_gate_mode or "warn")
    )
    governance_secrets_redact = (
        getattr(settings, "GOVERNANCE_SECRETS_REDACT", False)
        if options.governance_secrets_redact is None
        else bool(options.governance_secrets_redact)
    )
    governance_secrets_mode = (
        getattr(settings, "GOVERNANCE_SECRETS_MODE", "mask")
        if options.governance_secrets_mode is None
        else str(options.governance_secrets_mode or "mask")
    )
    governance_secrets_mask = (
        getattr(settings, "GOVERNANCE_SECRETS_MASK", DEFAULT_GOVERNANCE_SECRETS_MASK)
        if options.governance_secrets_mask is None
        else str(options.governance_secrets_mask or DEFAULT_GOVERNANCE_SECRETS_MASK)
    )
    governance_secrets_max_hits = (
        options.governance_secrets_max_hits
        if options.governance_secrets_max_hits is not None
        else int(settings.GOVERNANCE_SECRETS_MAX_HITS)
    )
    governance_max_blank_lines = (
        options.governance_max_blank_lines
        if options.governance_max_blank_lines is not None
        else int(getattr(settings, "GOVERNANCE_MAX_BLANK_LINES", 1) or 1)
    )
    governance_html_xpath = (
        getattr(settings, "GOVERNANCE_HTML_XPATH", "")
        if options.governance_html_xpath is None
        else str(options.governance_html_xpath or "")
    )
    governance_drop_outline_only = (
        getattr(settings, "GOVERNANCE_DROP_OUTLINE_ONLY", False)
        if options.governance_drop_outline_only is None
        else bool(options.governance_drop_outline_only)
    )
    governance_drop_outline_min_content_chars = (
        options.governance_drop_outline_min_content_chars
        if options.governance_drop_outline_min_content_chars is not None
        else int(getattr(settings, "GOVERNANCE_DROP_OUTLINE_MIN_CONTENT_CHARS", 200) or 200)
    )
    governance_drop_outline_max_heading_ratio = (
        options.governance_drop_outline_max_heading_ratio
        if options.governance_drop_outline_max_heading_ratio is not None
        else float(getattr(settings, "GOVERNANCE_DROP_OUTLINE_MAX_HEADING_RATIO", 0.85) or 0.85)
    )
    governance_drop_low_density = (
        getattr(settings, "GOVERNANCE_DROP_LOW_DENSITY", False)
        if options.governance_drop_low_density is None
        else bool(options.governance_drop_low_density)
    )
    governance_drop_low_density_threshold = (
        options.governance_drop_low_density_threshold
        if options.governance_drop_low_density_threshold is not None
        else float(getattr(settings, "GOVERNANCE_DROP_LOW_DENSITY_THRESHOLD", 0.12) or 0.12)
    )
    governance_unwrap_max_line_length = (
        options.governance_unwrap_max_line_length
        if options.governance_unwrap_max_line_length is not None
        else settings.GOVERNANCE_UNWRAP_MAX_LINE_LENGTH
    )
    governance_noise_min_chars = (
        options.governance_noise_min_chars
        if options.governance_noise_min_chars is not None
        else settings.GOVERNANCE_NOISE_MIN_CHARS
    )
    governance_noise_ratio_threshold = (
        options.governance_noise_ratio_threshold
        if options.governance_noise_ratio_threshold is not None
        else settings.GOVERNANCE_NOISE_RATIO_THRESHOLD
    )
    governance_common_lines_min_docs = (
        options.governance_common_lines_min_docs
        if options.governance_common_lines_min_docs is not None
        else settings.GOVERNANCE_COMMON_LINES_MIN_DOCS
    )
    governance_common_lines_min_ratio = (
        options.governance_common_lines_min_ratio
        if options.governance_common_lines_min_ratio is not None
        else settings.GOVERNANCE_COMMON_LINES_MIN_RATIO
    )
    governance_python_plugin = _sanitize_stage_python_plugin_ref(options.governance_python_plugin, "governance") or ""
    governance_python_params = _sanitize_chunk_strategy_params(options.governance_python_params) or {}
    parse_fallback_enabled = (
        getattr(settings, "PARSE_FALLBACK_ENABLED", False)
        if options.parse_fallback_enabled is None
        else bool(options.parse_fallback_enabled)
    )
    parse_fallback_min_content_chars = (
        options.parse_fallback_min_content_chars
        if options.parse_fallback_min_content_chars is not None
        else int(getattr(settings, "PARSE_FALLBACK_MIN_CONTENT_CHARS", 120) or 120)
    )
    parse_fallback_min_parse_score = (
        options.parse_fallback_min_parse_score
        if options.parse_fallback_min_parse_score is not None
        else float(getattr(settings, "PARSE_FALLBACK_MIN_PARSE_SCORE", 0.55) or 0.55)
    )
    parse_fallback_max_retries = (
        options.parse_fallback_max_retries
        if options.parse_fallback_max_retries is not None
        else int(getattr(settings, "PARSE_FALLBACK_MAX_RETRIES", 1) or 1)
    )
    cross_page_merge_enabled = (
        getattr(settings, "CROSS_PAGE_MERGE_ENABLED", False)
        if options.cross_page_merge_enabled is None
        else bool(options.cross_page_merge_enabled)
    )
    cross_page_merge_max_page_gap = (
        options.cross_page_merge_max_page_gap
        if options.cross_page_merge_max_page_gap is not None
        else int(getattr(settings, "CROSS_PAGE_MERGE_MAX_PAGE_GAP", 1) or 1)
    )
    reading_order_enabled = (
        getattr(settings, "READING_ORDER_ENABLED", True)
        if options.reading_order_enabled is None
        else bool(options.reading_order_enabled)
    )
    parse_cache_enabled = (
        getattr(settings, "PARSE_CACHE_ENABLED", False)
        if options.parse_cache_enabled is None
        else bool(options.parse_cache_enabled)
    )
    parse_cache_ttl_sec = (
        options.parse_cache_ttl_sec
        if options.parse_cache_ttl_sec is not None
        else int(getattr(settings, "PARSE_CACHE_TTL_SEC", 86_400) or 86_400)
    )
    vlm_correction_enabled = (
        getattr(settings, "VLM_CORRECTION_ENABLED", False)
        if options.vlm_correction_enabled is None
        else bool(options.vlm_correction_enabled)
    )
    vlm_correction_min_table_score = (
        options.vlm_correction_min_table_score
        if options.vlm_correction_min_table_score is not None
        else float(getattr(settings, "VLM_CORRECTION_MIN_TABLE_SCORE", 0.6) or 0.6)
    )
    vlm_correction_max_pages = (
        options.vlm_correction_max_pages
        if options.vlm_correction_max_pages is not None
        else int(getattr(settings, "VLM_CORRECTION_MAX_PAGES", 2) or 2)
    )
    persist_parsed_content = (
        getattr(settings, "PERSIST_PARSED_CONTENT", False)
        if options.persist_parsed_content is None
        else bool(options.persist_parsed_content)
    )
    persist_parsed_content_max_chars = (
        options.persist_parsed_content_max_chars
        if options.persist_parsed_content_max_chars is not None
        else int(getattr(settings, "PERSIST_PARSED_CONTENT_MAX_CHARS", 200_000) or 200_000)
    )
    near_dedup_enabled = (
        getattr(settings, "NEAR_DEDUP_ENABLED", False)
        if options.near_dedup_enabled is None
        else bool(options.near_dedup_enabled)
    )
    near_dedup_hamming_threshold = (
        options.near_dedup_hamming_threshold
        if options.near_dedup_hamming_threshold is not None
        else int(getattr(settings, "NEAR_DEDUP_HAMMING_THRESHOLD", 3) or 3)
    )
    near_dedup_max_bucket_size = (
        options.near_dedup_max_bucket_size
        if options.near_dedup_max_bucket_size is not None
        else int(getattr(settings, "NEAR_DEDUP_MAX_BUCKET_SIZE", 256) or 256)
    )
    chunk_size = options.chunk_size if options.chunk_size is not None else settings.CHUNK_SIZE
    chunk_overlap = options.chunk_overlap if options.chunk_overlap is not None else settings.CHUNK_OVERLAP
    chunk_merge_small_min_chars = (
        options.chunk_merge_small_min_chars
        if options.chunk_merge_small_min_chars is not None
        else int(getattr(settings, "CHUNK_MERGE_SMALL_MIN_CHARS", 0) or 0)
    )
    chunk_strategy_params = (
        options.chunk_strategy_params
        if options.chunk_strategy_params is not None
        else None
    )
    chunk_strategy_params = _sanitize_chunk_strategy_params(chunk_strategy_params) or {}
    chunk_python_plugin = _sanitize_stage_python_plugin_ref(options.chunk_python_plugin, "chunk") or ""
    chunk_python_params = _sanitize_chunk_strategy_params(options.chunk_python_params) or {}
    kg_python_plugin = _sanitize_stage_python_plugin_ref(options.kg_python_plugin, "kg") or ""
    kg_python_params = _sanitize_chunk_strategy_params(options.kg_python_params) or {}
    embedding_context_prefix_enabled = (
        getattr(settings, "EMBEDDING_CONTEXT_PREFIX_ENABLED", False)
        if options.embedding_context_prefix_enabled is None
        else bool(options.embedding_context_prefix_enabled)
    )
    embedding_contextual_retrieval_enabled = (
        getattr(settings, "CONTEXTUAL_RETRIEVAL_ENABLED", False)
        if options.embedding_contextual_retrieval_enabled is None
        else bool(options.embedding_contextual_retrieval_enabled)
    )
    embedding_contextual_retrieval_lazy_mode = (
        getattr(settings, "CONTEXTUAL_RETRIEVAL_LAZY_MODE", False)
        if options.embedding_contextual_retrieval_lazy_mode is None
        else bool(options.embedding_contextual_retrieval_lazy_mode)
    )
    embedding_field_aware_enabled = (
        False if options.embedding_field_aware_enabled is None else bool(options.embedding_field_aware_enabled)
    )
    table_store_enabled = (
        getattr(settings, "TABLE_STORE_ENABLED", False)
        if options.table_store_enabled is None
        else bool(options.table_store_enabled)
    )
    table_store_max_rows = (
        options.table_store_max_rows
        if options.table_store_max_rows is not None
        else int(settings.TABLE_STORE_MAX_ROWS)
    )
    table_store_max_cols = (
        options.table_store_max_cols
        if options.table_store_max_cols is not None
        else int(settings.TABLE_STORE_MAX_COLS)
    )
    table_store_sample_rows = (
        options.table_store_sample_rows
        if options.table_store_sample_rows is not None
        else int(settings.TABLE_STORE_SAMPLE_ROWS)
    )
    table_store_auto_route = (
        getattr(settings, "TABLE_STORE_AUTO_ROUTE", False)
        if options.table_store_auto_route is None
        else bool(options.table_store_auto_route)
    )
    table_store_sidecar_exclusive_routing = (
        getattr(settings, "TABLE_STORE_SIDECAR_EXCLUSIVE_ROUTING", False)
        if options.table_store_sidecar_exclusive_routing is None
        else bool(options.table_store_sidecar_exclusive_routing)
    )
    table_store_auto_row_threshold = (
        options.table_store_auto_row_threshold
        if options.table_store_auto_row_threshold is not None
        else int(getattr(settings, "TABLE_STORE_AUTO_ROW_THRESHOLD", 5000) or 5000)
    )
    table_store_auto_col_threshold = (
        options.table_store_auto_col_threshold
        if options.table_store_auto_col_threshold is not None
        else int(getattr(settings, "TABLE_STORE_AUTO_COL_THRESHOLD", 80) or 80)
    )
    table_store_auto_sheet_threshold = (
        options.table_store_auto_sheet_threshold
        if options.table_store_auto_sheet_threshold is not None
        else int(getattr(settings, "TABLE_STORE_AUTO_SHEET_THRESHOLD", 5) or 5)
    )
    table_store_auto_file_bytes_threshold = (
        options.table_store_auto_file_bytes_threshold
        if options.table_store_auto_file_bytes_threshold is not None
        else int(getattr(settings, "TABLE_STORE_AUTO_FILE_BYTES_THRESHOLD", 5_000_000) or 5_000_000)
    )
    image_caption_enabled = (
        getattr(settings, "IMAGE_CAPTION_ENABLED", False)
        if options.image_caption_enabled is None
        else bool(options.image_caption_enabled)
    )
    image_ocr_enabled = (
        getattr(settings, "IMAGE_OCR_ENABLED", False)
        if options.image_ocr_enabled is None
        else bool(options.image_ocr_enabled)
    )
    image_ocr_max_chars = (
        options.image_ocr_max_chars
        if options.image_ocr_max_chars is not None
        else int(getattr(settings, "IMAGE_OCR_MAX_CHARS", 2000) or 2000)
    )
    image_ocr_max_images = (
        options.image_ocr_max_images
        if options.image_ocr_max_images is not None
        else int(getattr(settings, "IMAGE_OCR_MAX_IMAGES", 20) or 20)
    )
    image_ocr_max_chars = max(0, int(image_ocr_max_chars))
    image_ocr_max_images = max(0, int(image_ocr_max_images))

    return PipelineEffective(
        governance_enabled=governance_enabled,
        governance_remove_toc_lines=governance_remove_toc_lines,
        governance_remove_noise_lines=governance_remove_noise_lines,
        governance_unwrap_lines=governance_unwrap_lines,
        governance_remove_common_lines=governance_remove_common_lines,
        governance_remove_boilerplate=governance_remove_boilerplate,
        governance_remove_images=str(governance_remove_images or "none"),
        governance_rule_packs=list(governance_rule_packs or []),
        governance_regex_rules=list(governance_regex_rules or []),
        governance_extract_frontmatter=bool(governance_extract_frontmatter),
        governance_strip_frontmatter=bool(governance_strip_frontmatter),
        governance_detect_language=bool(governance_detect_language),
        governance_language_min_chars=int(governance_language_min_chars),
        governance_normalize_urls=bool(governance_normalize_urls),
        governance_normalize_urls_strip_tracking=bool(governance_normalize_urls_strip_tracking),
        governance_drop_duplicate_paragraphs=bool(governance_drop_duplicate_paragraphs),
        governance_drop_duplicate_paragraphs_min_occurrences=int(governance_drop_duplicate_paragraphs_min_occurrences),
        governance_drop_duplicate_paragraphs_min_chars=int(governance_drop_duplicate_paragraphs_min_chars),
        governance_drop_duplicate_paragraphs_max_chars=int(governance_drop_duplicate_paragraphs_max_chars),
        governance_trim_references=bool(governance_trim_references),
        governance_extract_keywords=bool(governance_extract_keywords),
        governance_keywords_provider=str(governance_keywords_provider or "auto"),
        governance_keywords_top_k=int(governance_keywords_top_k),
        governance_keywords_max_chars=int(governance_keywords_max_chars),
        governance_normalize_tables=bool(governance_normalize_tables),
        governance_strip_code_line_numbers=bool(governance_strip_code_line_numbers),
        governance_quarantine_on_drop=bool(governance_quarantine_on_drop),
        governance_pii_anonymize=bool(governance_pii_anonymize),
        governance_pii_mode=str(governance_pii_mode or "mask"),
        governance_pii_mask=str(governance_pii_mask or DEFAULT_GOVERNANCE_PII_MASK),
        governance_pii_max_hits=int(governance_pii_max_hits),
        governance_llm_auto_tagging_enabled=bool(governance_llm_auto_tagging_enabled),
        governance_llm_auto_tagging_max_chars=max(200, int(governance_llm_auto_tagging_max_chars or 3000)),
        governance_llm_auto_tagging_max_items=max(1, int(governance_llm_auto_tagging_max_items or 16)),
        ingest_pre_poc_scanner_enabled=bool(ingest_pre_poc_scanner_enabled),
        ingest_pre_poc_quality_gate_mode=_normalize_pre_poc_quality_gate_mode(ingest_pre_poc_quality_gate_mode),
        governance_secrets_redact=bool(governance_secrets_redact),
        governance_secrets_mode=str(governance_secrets_mode or "mask"),
        governance_secrets_mask=str(governance_secrets_mask or DEFAULT_GOVERNANCE_SECRETS_MASK),
        governance_secrets_max_hits=int(governance_secrets_max_hits),
        governance_max_blank_lines=int(governance_max_blank_lines),
        governance_html_xpath=str(governance_html_xpath or ""),
        governance_drop_outline_only=bool(governance_drop_outline_only),
        governance_drop_outline_min_content_chars=int(governance_drop_outline_min_content_chars),
        governance_drop_outline_max_heading_ratio=float(governance_drop_outline_max_heading_ratio),
        governance_drop_low_density=bool(governance_drop_low_density),
        governance_drop_low_density_threshold=float(governance_drop_low_density_threshold),
        governance_unwrap_max_line_length=int(governance_unwrap_max_line_length),
        governance_noise_min_chars=int(governance_noise_min_chars),
        governance_noise_ratio_threshold=float(governance_noise_ratio_threshold),
        governance_common_lines_min_docs=int(governance_common_lines_min_docs),
        governance_common_lines_min_ratio=float(governance_common_lines_min_ratio),
        governance_python_plugin=str(governance_python_plugin or ""),
        governance_python_params=dict(governance_python_params),
        parse_fallback_enabled=bool(parse_fallback_enabled),
        parse_fallback_min_content_chars=int(parse_fallback_min_content_chars),
        parse_fallback_min_parse_score=float(parse_fallback_min_parse_score),
        parse_fallback_max_retries=int(parse_fallback_max_retries),
        cross_page_merge_enabled=bool(cross_page_merge_enabled),
        cross_page_merge_max_page_gap=int(cross_page_merge_max_page_gap),
        reading_order_enabled=bool(reading_order_enabled),
        parse_cache_enabled=bool(parse_cache_enabled),
        parse_cache_ttl_sec=int(parse_cache_ttl_sec),
        vlm_correction_enabled=bool(vlm_correction_enabled),
        vlm_correction_min_table_score=float(vlm_correction_min_table_score),
        vlm_correction_max_pages=int(vlm_correction_max_pages),
        persist_parsed_content=bool(persist_parsed_content),
        persist_parsed_content_max_chars=int(persist_parsed_content_max_chars),
        near_dedup_enabled=bool(near_dedup_enabled),
        near_dedup_hamming_threshold=int(near_dedup_hamming_threshold),
        near_dedup_max_bucket_size=int(near_dedup_max_bucket_size),
        chunk_size=int(chunk_size),
        chunk_overlap=int(chunk_overlap),
        chunk_merge_small_min_chars=int(chunk_merge_small_min_chars),
        chunk_strategy_params=dict(chunk_strategy_params),
        chunk_python_plugin=str(chunk_python_plugin or ""),
        chunk_python_params=dict(chunk_python_params),
        embedding_context_prefix_enabled=bool(embedding_context_prefix_enabled),
        embedding_contextual_retrieval_enabled=bool(embedding_contextual_retrieval_enabled),
        embedding_contextual_retrieval_lazy_mode=bool(embedding_contextual_retrieval_lazy_mode),
        embedding_field_aware_enabled=bool(embedding_field_aware_enabled),
        chunk_vector_enabled=_resolve_flag(settings.CHUNK_VECTOR_ENABLED, options.chunk_vector_enabled),
        bm25_index_enabled=_resolve_flag(settings.BM25_INDEX_ENABLED, options.bm25_index_enabled),
        kg_enabled=_resolve_flag(settings.KG_ENABLED, options.kg_enabled),
        kg_python_plugin=str(kg_python_plugin or ""),
        kg_python_params=dict(kg_python_params),
        event_vector_enabled=_resolve_flag(settings.EVENT_VECTOR_ENABLED, options.event_vector_enabled),
        entity_vector_enabled=_resolve_flag(settings.ENTITY_VECTOR_ENABLED, options.entity_vector_enabled),
        table_store_enabled=bool(table_store_enabled),
        table_store_max_rows=int(table_store_max_rows),
        table_store_max_cols=int(table_store_max_cols),
        table_store_sample_rows=int(table_store_sample_rows),
        table_store_auto_route=bool(table_store_auto_route),
        table_store_sidecar_exclusive_routing=bool(table_store_sidecar_exclusive_routing),
        table_store_auto_row_threshold=int(table_store_auto_row_threshold),
        table_store_auto_col_threshold=int(table_store_auto_col_threshold),
        table_store_auto_sheet_threshold=int(table_store_auto_sheet_threshold),
        table_store_auto_file_bytes_threshold=int(table_store_auto_file_bytes_threshold),
        image_caption_enabled=bool(image_caption_enabled),
        image_ocr_enabled=bool(image_ocr_enabled),
        image_ocr_max_chars=int(image_ocr_max_chars),
        image_ocr_max_images=int(image_ocr_max_images),
    )


def build_indexing_options(effective: PipelineEffective) -> IndexingOptions:
    """Build indexing options from the effective configuration."""
    return IndexingOptions(
        chunk_vector_enabled=effective.chunk_vector_enabled,
        bm25_index_enabled=effective.bm25_index_enabled,
        event_vector_enabled=effective.event_vector_enabled,
        entity_vector_enabled=effective.entity_vector_enabled,
        embedding_context_prefix_enabled=effective.embedding_context_prefix_enabled,
        embedding_contextual_retrieval_enabled=effective.embedding_contextual_retrieval_enabled,
        embedding_contextual_retrieval_lazy_mode=effective.embedding_contextual_retrieval_lazy_mode,
        embedding_field_aware_enabled=effective.embedding_field_aware_enabled,
    )
