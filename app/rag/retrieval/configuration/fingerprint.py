"""
Stable, PII-safe retrieval config fingerprinting.

Used to compare retrieval runs across environments without persisting raw queries
or scope identifiers (tenant/dataset/document ids).
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from app.infrastructure.hashing import stable_json_dumps, stable_json_hash
from app.infrastructure.metadata_filters import summarize_metadata_filter

if TYPE_CHECKING:
    from app.rag.retrieval.configuration.options import HybridSearchOptions
    from app.rag.retrieval.recall.retriever import HybridRetriever


_BANNED_KEYS = {
    # Text-like (potential PII / content leakage)
    "question",
    "query",
    "query_for_retrieval",
    "history",
    # Scope identifiers (high-cardinality; potential leakage)
    "tenant_id",
    "account_id",
    "user_id",
    "dataset_id",
    "dataset_ids",
    "document_id",
    "document_ids",
    "table_ids",
    # Filters can embed identifiers / PII-like values
    "metadata_filter",
}


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return _normalize_mapping(value)
    if isinstance(value, (list, tuple, set)):
        return _normalize_sequence(value)

    raise TypeError("Retrieval config values must be JSON-compatible")


def _normalize_mapping(value: Mapping[str, Any]) -> dict[str, Any] | None:
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = raw_key.strip()
        if not key or key in _BANNED_KEYS:
            continue
        item = _normalize_value(raw_value)
        if item is not None:
            normalized[key] = item
    return normalized or None


def _normalize_sequence(value: list[Any] | tuple[Any, ...] | set[Any]) -> list[Any] | None:
    normalized = []
    for raw_item in value:
        item = _normalize_value(raw_item)
        if item is not None:
            normalized.append(item)
    if isinstance(value, set):
        normalized.sort(key=stable_json_dumps)
    return normalized or None


def build_retrieval_config_fingerprint(
    *, config: dict[str, Any], schema: str = "mimirq.retrieval_config.v1"
) -> dict[str, Any]:
    """
    Build a stable fingerprint for a retrieval config.

    Returns:
        {"schema": ..., "hash": ..., "config": ...}

    Notes:
    - `config` is normalized and stripped of banned/sensitive keys.
    - The hash is stable across restarts (SHA-256 via stable_hash()).
    """
    cleaned = _normalize_mapping(config) or {}
    metadata_filter = config.get("metadata_filter")
    if isinstance(metadata_filter, dict) and metadata_filter:
        cleaned["metadata_filter_hash"] = stable_json_hash(metadata_filter, length=32)
        metadata_summary = summarize_metadata_filter(metadata_filter)
        if metadata_summary:
            cleaned["metadata_filter_summary"] = metadata_summary

    digest = stable_json_hash(cleaned, length=32)
    return {
        "schema": schema.strip() or "mimirq.retrieval_config.v1",
        "hash": digest,
        "config": cleaned,
    }


def retrieval_cache_runtime_values() -> dict[str, Any]:
    """Bind candidate, semantic and answer caches to the same retrieval configuration."""
    from app.infrastructure.config import settings

    prefixes = ("BM25_", "MILVUS_BM25_", "LEXICAL_", "RERANK", "RETRIEVAL_")
    return {
        key: value
        for key, value in settings.model_dump(mode="json").items()
        if key.startswith(prefixes) or key == "VECTOR_BACKEND"
    }


def _build_retrieval_cache_behavior_hash(
    *,
    retriever: "HybridRetriever",
    options: "HybridSearchOptions",
) -> str:
    option_values = asdict(options)
    if options.document_ids:
        option_values["document_ids"] = sorted({str(document_id) for document_id in options.document_ids})
    runtime = retrieval_cache_runtime_values()
    return stable_json_hash(
        {"options": option_values, "retriever": retriever.model_dump(mode="json"), "runtime": runtime},
        length=24,
    )


@dataclass(frozen=True)
class RetrievalConfigSnapshotInput:
    retrieval_config: Mapping[str, Any]
    rag_config_template: Mapping[str, Any] | None


@dataclass(frozen=True)
class RetrievalConfigSnapshotOutput:
    fingerprint: dict[str, Any]


def _normalize_rag_config_template(raw: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    return {
        key: value
        for key, value in raw.items()
        if key in ("template_key", "version", "ab_experiment_key", "ab_variant", "patch_hash")
    }


def build_retrieval_config_snapshot(payload: RetrievalConfigSnapshotInput) -> RetrievalConfigSnapshotOutput:
    config = dict(payload.retrieval_config)
    rag_config_template = _normalize_rag_config_template(payload.rag_config_template)
    if rag_config_template is not None:
        config["rag_config_template"] = rag_config_template
    return RetrievalConfigSnapshotOutput(fingerprint=build_retrieval_config_fingerprint(config=config))


__all__ = [
    "RetrievalConfigSnapshotInput",
    "RetrievalConfigSnapshotOutput",
    "build_retrieval_config_fingerprint",
    "build_retrieval_config_snapshot",
    "retrieval_cache_runtime_values",
]
