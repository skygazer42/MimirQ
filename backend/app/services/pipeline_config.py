from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.config import settings
from app.services.indexer import IndexingOptions


@dataclass(frozen=True)
class PipelineOptions:
    governance_enabled: Optional[bool] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    chunk_vector_enabled: Optional[bool] = None
    bm25_index_enabled: Optional[bool] = None
    sag_enabled: Optional[bool] = None
    event_vector_enabled: Optional[bool] = None
    entity_vector_enabled: Optional[bool] = None


@dataclass(frozen=True)
class PipelineEffective:
    governance_enabled: bool
    chunk_size: int
    chunk_overlap: int
    chunk_vector_enabled: bool
    bm25_index_enabled: bool
    sag_enabled: bool
    event_vector_enabled: bool
    entity_vector_enabled: bool


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

    return PipelineOptions(
        governance_enabled=_coerce_bool(pipeline.get("governance_enabled")),
        chunk_size=_coerce_int(pipeline.get("chunk_size")),
        chunk_overlap=_coerce_int(pipeline.get("chunk_overlap")),
        chunk_vector_enabled=_coerce_bool(index.get("chunk_vector_enabled")),
        bm25_index_enabled=_coerce_bool(index.get("bm25_index_enabled")),
        sag_enabled=_coerce_bool(index.get("sag_enabled")),
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

    index: Dict[str, Any] = {}
    if options.chunk_vector_enabled is not None:
        index["chunk_vector_enabled"] = bool(options.chunk_vector_enabled)
    if options.bm25_index_enabled is not None:
        index["bm25_index_enabled"] = bool(options.bm25_index_enabled)
    if options.sag_enabled is not None:
        index["sag_enabled"] = bool(options.sag_enabled)
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
    chunk_size = options.chunk_size if options.chunk_size is not None else settings.CHUNK_SIZE
    chunk_overlap = options.chunk_overlap if options.chunk_overlap is not None else settings.CHUNK_OVERLAP

    return PipelineEffective(
        governance_enabled=governance_enabled,
        chunk_size=int(chunk_size),
        chunk_overlap=int(chunk_overlap),
        chunk_vector_enabled=_resolve_flag(settings.CHUNK_VECTOR_ENABLED, options.chunk_vector_enabled),
        bm25_index_enabled=_resolve_flag(settings.BM25_INDEX_ENABLED, options.bm25_index_enabled),
        sag_enabled=_resolve_flag(settings.SAG_ENABLED, options.sag_enabled),
        event_vector_enabled=_resolve_flag(settings.EVENT_VECTOR_ENABLED, options.event_vector_enabled),
        entity_vector_enabled=_resolve_flag(settings.ENTITY_VECTOR_ENABLED, options.entity_vector_enabled),
    )


def build_indexing_options(effective: PipelineEffective) -> IndexingOptions:
    return IndexingOptions(
        chunk_vector_enabled=effective.chunk_vector_enabled,
        bm25_index_enabled=effective.bm25_index_enabled,
        event_vector_enabled=effective.event_vector_enabled,
        entity_vector_enabled=effective.entity_vector_enabled,
    )
