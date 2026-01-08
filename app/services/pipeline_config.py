"""
Pipeline configuration service.

Provides parsing, building, and resolution for pipeline configuration.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.types.indexing import IndexingOptions
from app.types.pipeline import PipelineEffective, PipelineOptions
from app.core.config import settings


def _coerce_bool(value: Any) -> Optional[bool]:
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


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _resolve_flag(default: bool, override: Optional[bool]) -> bool:
    if override is None:
        return bool(default)
    if override:
        return bool(default)
    return False


def parse_pipeline_from_metadata(metadata: Dict[str, Any]) -> PipelineOptions:
    if not isinstance(metadata, dict):
        return PipelineOptions()
    pipeline = metadata.get("pipeline")
    if not isinstance(pipeline, dict):
        return PipelineOptions()

    index = pipeline.get("index")
    if not isinstance(index, dict):
        index = {}
    governance = pipeline.get("governance")
    if not isinstance(governance, dict):
        governance = {}

    return PipelineOptions(
        governance_enabled=_coerce_bool(pipeline.get("governance_enabled")),
        governance_remove_toc_lines=_coerce_bool(governance.get("remove_toc_lines")),
        governance_remove_noise_lines=_coerce_bool(governance.get("remove_noise_lines")),
        governance_unwrap_lines=_coerce_bool(governance.get("unwrap_lines")),
        governance_remove_common_lines=_coerce_bool(governance.get("remove_common_lines")),
        governance_unwrap_max_line_length=_coerce_int(governance.get("unwrap_max_line_length")),
        governance_noise_min_chars=_coerce_int(governance.get("noise_min_chars")),
        governance_noise_ratio_threshold=_coerce_float(governance.get("noise_ratio_threshold")),
        governance_common_lines_min_docs=_coerce_int(governance.get("common_lines_min_docs")),
        governance_common_lines_min_ratio=_coerce_float(governance.get("common_lines_min_ratio")),
        chunk_size=_coerce_int(pipeline.get("chunk_size")),
        chunk_overlap=_coerce_int(pipeline.get("chunk_overlap")),
        chunk_vector_enabled=_coerce_bool(index.get("chunk_vector_enabled")),
        bm25_index_enabled=_coerce_bool(index.get("bm25_index_enabled")),
        kg_enabled=_coerce_bool(index.get("kg_enabled")),
        event_vector_enabled=_coerce_bool(index.get("event_vector_enabled")),
        entity_vector_enabled=_coerce_bool(index.get("entity_vector_enabled")),
    )


def build_pipeline_metadata(options: PipelineOptions) -> Optional[Dict[str, Any]]:
    if options is None:
        return None

    pipeline: Dict[str, Any] = {}
    if options.governance_enabled is not None:
        pipeline["governance_enabled"] = bool(options.governance_enabled)
    if options.chunk_size is not None:
        pipeline["chunk_size"] = int(options.chunk_size)
    if options.chunk_overlap is not None:
        pipeline["chunk_overlap"] = int(options.chunk_overlap)

    governance: Dict[str, Any] = {}
    if options.governance_remove_toc_lines is not None:
        governance["remove_toc_lines"] = bool(options.governance_remove_toc_lines)
    if options.governance_remove_noise_lines is not None:
        governance["remove_noise_lines"] = bool(options.governance_remove_noise_lines)
    if options.governance_unwrap_lines is not None:
        governance["unwrap_lines"] = bool(options.governance_unwrap_lines)
    if options.governance_remove_common_lines is not None:
        governance["remove_common_lines"] = bool(options.governance_remove_common_lines)
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
    if governance:
        pipeline["governance"] = governance

    index: Dict[str, Any] = {}
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
    if index:
        pipeline["index"] = index

    return pipeline or None


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
    chunk_size = options.chunk_size if options.chunk_size is not None else settings.CHUNK_SIZE
    chunk_overlap = options.chunk_overlap if options.chunk_overlap is not None else settings.CHUNK_OVERLAP

    return PipelineEffective(
        governance_enabled=governance_enabled,
        governance_remove_toc_lines=governance_remove_toc_lines,
        governance_remove_noise_lines=governance_remove_noise_lines,
        governance_unwrap_lines=governance_unwrap_lines,
        governance_remove_common_lines=governance_remove_common_lines,
        governance_unwrap_max_line_length=int(governance_unwrap_max_line_length),
        governance_noise_min_chars=int(governance_noise_min_chars),
        governance_noise_ratio_threshold=float(governance_noise_ratio_threshold),
        governance_common_lines_min_docs=int(governance_common_lines_min_docs),
        governance_common_lines_min_ratio=float(governance_common_lines_min_ratio),
        chunk_size=int(chunk_size),
        chunk_overlap=int(chunk_overlap),
        chunk_vector_enabled=_resolve_flag(settings.CHUNK_VECTOR_ENABLED, options.chunk_vector_enabled),
        bm25_index_enabled=_resolve_flag(settings.BM25_INDEX_ENABLED, options.bm25_index_enabled),
        kg_enabled=_resolve_flag(settings.KG_ENABLED, options.kg_enabled),
        event_vector_enabled=_resolve_flag(settings.EVENT_VECTOR_ENABLED, options.event_vector_enabled),
        entity_vector_enabled=_resolve_flag(settings.ENTITY_VECTOR_ENABLED, options.entity_vector_enabled),
    )


def build_indexing_options(effective: PipelineEffective) -> IndexingOptions:
    """Build indexing options from the effective configuration."""
    return IndexingOptions(
        chunk_vector_enabled=effective.chunk_vector_enabled,
        bm25_index_enabled=effective.bm25_index_enabled,
        event_vector_enabled=effective.event_vector_enabled,
        entity_vector_enabled=effective.entity_vector_enabled,
    )
