"""
Pipeline configuration service.

Provides parsing, building, and resolution for pipeline configuration.
"""

import re
from dataclasses import asdict
from typing import Any

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
        if not isinstance(item, dict):
            continue
        pattern = item.get("pattern")
        if not isinstance(pattern, str):
            continue
        pattern = pattern.strip()
        if not pattern:
            continue
        if len(pattern) > _REGEX_PATTERN_MAX:
            continue
        if looks_like_nested_quantifier(pattern):
            continue

        repl = item.get("repl", "")
        if repl is None:
            repl = ""
        if not isinstance(repl, str):
            repl = str(repl)
        if len(repl) > _REGEX_REPL_MAX:
            repl = repl[:_REGEX_REPL_MAX]

        flags = item.get("flags", 0)
        try:
            flags_int = int(flags)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if flags_int < 0 or (flags_int & ~_ALLOWED_RE_FLAG_BITS):
            continue
        try:
            re.compile(pattern, flags=flags_int)
        except re.error:
            continue

        out.append({"pattern": pattern, "repl": repl, "flags": flags_int})
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
    if options.governance_enabled is not None:
        pipeline["governance_enabled"] = bool(options.governance_enabled)
    if options.parse_fallback_enabled is not None:
        pipeline["parse_fallback_enabled"] = bool(options.parse_fallback_enabled)
    if options.parse_fallback_min_content_chars is not None:
        pipeline["parse_fallback_min_content_chars"] = int(options.parse_fallback_min_content_chars)
    if options.parse_fallback_min_parse_score is not None:
        pipeline["parse_fallback_min_parse_score"] = float(options.parse_fallback_min_parse_score)
    if options.parse_fallback_max_retries is not None:
        pipeline["parse_fallback_max_retries"] = int(options.parse_fallback_max_retries)
    if options.cross_page_merge_enabled is not None:
        pipeline["cross_page_merge_enabled"] = bool(options.cross_page_merge_enabled)
    if options.cross_page_merge_max_page_gap is not None:
        pipeline["cross_page_merge_max_page_gap"] = int(options.cross_page_merge_max_page_gap)
    if options.reading_order_enabled is not None:
        pipeline["reading_order_enabled"] = bool(options.reading_order_enabled)
    if options.parse_cache_enabled is not None:
        pipeline["parse_cache_enabled"] = bool(options.parse_cache_enabled)
    if options.parse_cache_ttl_sec is not None:
        pipeline["parse_cache_ttl_sec"] = int(options.parse_cache_ttl_sec)
    if options.vlm_correction_enabled is not None:
        pipeline["vlm_correction_enabled"] = bool(options.vlm_correction_enabled)
    if options.vlm_correction_min_table_score is not None:
        pipeline["vlm_correction_min_table_score"] = float(options.vlm_correction_min_table_score)
    if options.vlm_correction_max_pages is not None:
        pipeline["vlm_correction_max_pages"] = int(options.vlm_correction_max_pages)
    if options.persist_parsed_content is not None:
        pipeline["persist_parsed_content"] = bool(options.persist_parsed_content)
    if options.persist_parsed_content_max_chars is not None:
        pipeline["persist_parsed_content_max_chars"] = int(options.persist_parsed_content_max_chars)
    if options.chunk_size is not None:
        pipeline["chunk_size"] = int(options.chunk_size)
    if options.chunk_overlap is not None:
        pipeline["chunk_overlap"] = int(options.chunk_overlap)
    if options.chunk_merge_small_min_chars is not None:
        pipeline["chunk_merge_small_min_chars"] = int(options.chunk_merge_small_min_chars)
    if options.chunk_strategy_params is not None:
        sanitized = _sanitize_chunk_strategy_params(options.chunk_strategy_params)
        if sanitized:
            pipeline["chunk_strategy_params"] = sanitized
    if options.chunk_python_plugin is not None:
        plugin_ref = _sanitize_stage_python_plugin_ref(options.chunk_python_plugin, "chunk")
        if plugin_ref:
            pipeline["chunk_python_plugin"] = plugin_ref
    if options.chunk_python_params is not None:
        sanitized = _sanitize_chunk_strategy_params(options.chunk_python_params)
        if sanitized:
            pipeline["chunk_python_params"] = sanitized
    if options.kg_python_plugin is not None:
        plugin_ref = _sanitize_stage_python_plugin_ref(options.kg_python_plugin, "kg")
        if plugin_ref:
            pipeline["kg_python_plugin"] = plugin_ref
    if options.kg_python_params is not None:
        sanitized = _sanitize_chunk_strategy_params(options.kg_python_params)
        if sanitized:
            pipeline["kg_python_params"] = sanitized

    tables: dict[str, Any] = {}
    if options.table_store_enabled is not None:
        tables["enabled"] = bool(options.table_store_enabled)
    if options.table_store_max_rows is not None:
        tables["max_rows"] = int(options.table_store_max_rows)
    if options.table_store_max_cols is not None:
        tables["max_cols"] = int(options.table_store_max_cols)
    if options.table_store_sample_rows is not None:
        tables["sample_rows"] = int(options.table_store_sample_rows)
    if options.table_store_auto_route is not None:
        tables["auto_route"] = bool(options.table_store_auto_route)
    if options.table_store_sidecar_exclusive_routing is not None:
        tables["sidecar_exclusive_routing"] = bool(options.table_store_sidecar_exclusive_routing)
    if options.table_store_auto_row_threshold is not None:
        tables["auto_row_threshold"] = int(options.table_store_auto_row_threshold)
    if options.table_store_auto_col_threshold is not None:
        tables["auto_col_threshold"] = int(options.table_store_auto_col_threshold)
    if options.table_store_auto_sheet_threshold is not None:
        tables["auto_sheet_threshold"] = int(options.table_store_auto_sheet_threshold)
    if options.table_store_auto_file_bytes_threshold is not None:
        tables["auto_file_bytes_threshold"] = int(options.table_store_auto_file_bytes_threshold)
    if tables:
        pipeline["tables"] = tables

    images: dict[str, Any] = {}
    if options.image_caption_enabled is not None:
        images["caption_enabled"] = bool(options.image_caption_enabled)
    if options.image_ocr_enabled is not None:
        images["ocr_enabled"] = bool(options.image_ocr_enabled)
    if options.image_ocr_max_chars is not None:
        images["ocr_max_chars"] = int(options.image_ocr_max_chars)
    if options.image_ocr_max_images is not None:
        images["ocr_max_images"] = int(options.image_ocr_max_images)
    if images:
        pipeline["images"] = images

    governance: dict[str, Any] = {}
    if options.governance_remove_toc_lines is not None:
        governance["remove_toc_lines"] = bool(options.governance_remove_toc_lines)
    if options.governance_remove_noise_lines is not None:
        governance["remove_noise_lines"] = bool(options.governance_remove_noise_lines)
    if options.governance_unwrap_lines is not None:
        governance["unwrap_lines"] = bool(options.governance_unwrap_lines)
    if options.governance_remove_common_lines is not None:
        governance["remove_common_lines"] = bool(options.governance_remove_common_lines)
    if options.governance_remove_boilerplate is not None:
        governance["remove_boilerplate"] = bool(options.governance_remove_boilerplate)
    if options.governance_remove_images is not None:
        governance["remove_images"] = str(options.governance_remove_images)
    if options.governance_rule_packs is not None:
        sanitized = _sanitize_rule_packs(options.governance_rule_packs)
        if sanitized:
            governance["rule_packs"] = sanitized
    if options.governance_regex_rules is not None:
        sanitized = _sanitize_regex_rules(options.governance_regex_rules)
        if sanitized:
            governance["regex_rules"] = sanitized
    if options.governance_extract_frontmatter is not None:
        governance["extract_frontmatter"] = bool(options.governance_extract_frontmatter)
    if options.governance_strip_frontmatter is not None:
        governance["strip_frontmatter"] = bool(options.governance_strip_frontmatter)
    if options.governance_detect_language is not None:
        governance["detect_language"] = bool(options.governance_detect_language)
    if options.governance_language_min_chars is not None:
        governance["language_min_chars"] = int(options.governance_language_min_chars)
    if options.governance_normalize_urls is not None:
        governance["normalize_urls"] = bool(options.governance_normalize_urls)
    if options.governance_normalize_urls_strip_tracking is not None:
        governance["normalize_urls_strip_tracking"] = bool(options.governance_normalize_urls_strip_tracking)
    if options.governance_drop_duplicate_paragraphs is not None:
        governance["drop_duplicate_paragraphs"] = bool(options.governance_drop_duplicate_paragraphs)
    if options.governance_drop_duplicate_paragraphs_min_occurrences is not None:
        governance["drop_duplicate_paragraphs_min_occurrences"] = int(options.governance_drop_duplicate_paragraphs_min_occurrences)
    if options.governance_drop_duplicate_paragraphs_min_chars is not None:
        governance["drop_duplicate_paragraphs_min_chars"] = int(options.governance_drop_duplicate_paragraphs_min_chars)
    if options.governance_drop_duplicate_paragraphs_max_chars is not None:
        governance["drop_duplicate_paragraphs_max_chars"] = int(options.governance_drop_duplicate_paragraphs_max_chars)
    if options.governance_trim_references is not None:
        governance["trim_references"] = bool(options.governance_trim_references)
    if options.governance_extract_keywords is not None:
        governance["extract_keywords"] = bool(options.governance_extract_keywords)
    if options.governance_keywords_provider is not None:
        governance["keywords_provider"] = str(options.governance_keywords_provider)
    if options.governance_keywords_top_k is not None:
        governance["keywords_top_k"] = int(options.governance_keywords_top_k)
    if options.governance_keywords_max_chars is not None:
        governance["keywords_max_chars"] = int(options.governance_keywords_max_chars)
    if options.governance_normalize_tables is not None:
        governance["normalize_tables"] = bool(options.governance_normalize_tables)
    if options.governance_strip_code_line_numbers is not None:
        governance["strip_code_line_numbers"] = bool(options.governance_strip_code_line_numbers)
    if options.governance_quarantine_on_drop is not None:
        governance["quarantine_on_drop"] = bool(options.governance_quarantine_on_drop)
    if options.governance_pii_anonymize is not None:
        governance["pii_anonymize"] = bool(options.governance_pii_anonymize)
    if options.governance_pii_mode is not None:
        governance["pii_mode"] = str(options.governance_pii_mode)
    if options.governance_pii_mask is not None:
        governance["pii_mask"] = str(options.governance_pii_mask)
    if options.governance_pii_max_hits is not None:
        governance["pii_max_hits"] = int(options.governance_pii_max_hits)
    if options.governance_llm_auto_tagging_enabled is not None:
        governance["llm_auto_tagging_enabled"] = bool(options.governance_llm_auto_tagging_enabled)
    if options.governance_llm_auto_tagging_max_chars is not None:
        governance["llm_auto_tagging_max_chars"] = int(options.governance_llm_auto_tagging_max_chars)
    if options.governance_llm_auto_tagging_max_items is not None:
        governance["llm_auto_tagging_max_items"] = int(options.governance_llm_auto_tagging_max_items)
    pre_poc: dict[str, Any] = {}
    if options.ingest_pre_poc_scanner_enabled is not None:
        pre_poc["scanner_enabled"] = bool(options.ingest_pre_poc_scanner_enabled)
    if options.ingest_pre_poc_quality_gate_mode is not None:
        pre_poc["quality_gate_mode"] = str(options.ingest_pre_poc_quality_gate_mode)
    if pre_poc:
        pipeline["pre_poc"] = pre_poc
    if options.governance_secrets_redact is not None:
        governance["secrets_redact"] = bool(options.governance_secrets_redact)
    if options.governance_secrets_mode is not None:
        governance["secrets_mode"] = str(options.governance_secrets_mode)
    if options.governance_secrets_mask is not None:
        governance["secrets_mask"] = str(options.governance_secrets_mask)
    if options.governance_secrets_max_hits is not None:
        governance["secrets_max_hits"] = int(options.governance_secrets_max_hits)
    if options.governance_max_blank_lines is not None:
        governance["max_blank_lines"] = int(options.governance_max_blank_lines)
    if options.governance_html_xpath is not None:
        governance["html_xpath"] = str(options.governance_html_xpath)
    if options.governance_drop_outline_only is not None:
        governance["drop_outline_only"] = bool(options.governance_drop_outline_only)
    if options.governance_drop_outline_min_content_chars is not None:
        governance["drop_outline_min_content_chars"] = int(options.governance_drop_outline_min_content_chars)
    if options.governance_drop_outline_max_heading_ratio is not None:
        governance["drop_outline_max_heading_ratio"] = float(options.governance_drop_outline_max_heading_ratio)
    if options.governance_drop_low_density is not None:
        governance["drop_low_density"] = bool(options.governance_drop_low_density)
    if options.governance_drop_low_density_threshold is not None:
        governance["drop_low_density_threshold"] = float(options.governance_drop_low_density_threshold)
    if options.governance_unwrap_max_line_length is not None:
        governance["unwrap_max_line_length"] = int(options.governance_unwrap_max_line_length)
    if options.governance_noise_min_chars is not None:
        governance["noise_min_chars"] = int(options.governance_noise_min_chars)
    if options.governance_noise_ratio_threshold is not None:
        governance["noise_ratio_threshold"] = float(options.governance_noise_ratio_threshold)
    if options.governance_common_lines_min_docs is not None:
        governance["common_lines_min_docs"] = int(options.governance_common_lines_min_docs)
    if options.governance_common_lines_min_ratio is not None:
        governance["common_lines_min_ratio"] = float(options.governance_common_lines_min_ratio)
    if options.governance_python_plugin is not None:
        plugin_ref = _sanitize_stage_python_plugin_ref(options.governance_python_plugin, "governance")
        if plugin_ref:
            governance["python_plugin"] = plugin_ref
    if options.governance_python_params is not None:
        sanitized = _sanitize_chunk_strategy_params(options.governance_python_params)
        if sanitized:
            governance["python_params"] = sanitized
    if governance:
        pipeline["governance"] = governance

    dedup: dict[str, Any] = {}
    if options.near_dedup_enabled is not None:
        dedup["enabled"] = bool(options.near_dedup_enabled)
    if options.near_dedup_hamming_threshold is not None:
        dedup["hamming_threshold"] = int(options.near_dedup_hamming_threshold)
    if options.near_dedup_max_bucket_size is not None:
        dedup["max_bucket_size"] = int(options.near_dedup_max_bucket_size)
    if dedup:
        pipeline["dedup"] = dedup

    index: dict[str, Any] = {}
    if options.chunk_vector_enabled is not None:
        index["chunk_vector_enabled"] = bool(options.chunk_vector_enabled)
    if options.bm25_index_enabled is not None:
        index["bm25_index_enabled"] = bool(options.bm25_index_enabled)
    if options.kg_enabled is not None:
        index["kg_enabled"] = bool(options.kg_enabled)
    if options.event_vector_enabled is not None:
        index["event_vector_enabled"] = bool(options.event_vector_enabled)
    if options.entity_vector_enabled is not None:
        index["entity_vector_enabled"] = bool(options.entity_vector_enabled)
    if options.embedding_context_prefix_enabled is not None:
        index["embedding_context_prefix_enabled"] = bool(options.embedding_context_prefix_enabled)
    if options.embedding_contextual_retrieval_enabled is not None:
        index["embedding_contextual_retrieval_enabled"] = bool(options.embedding_contextual_retrieval_enabled)
    if options.embedding_contextual_retrieval_lazy_mode is not None:
        index["embedding_contextual_retrieval_lazy_mode"] = bool(options.embedding_contextual_retrieval_lazy_mode)
    if options.embedding_field_aware_enabled is not None:
        index["embedding_field_aware_enabled"] = bool(options.embedding_field_aware_enabled)
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
