"""
Stable, PII-safe retrieval config fingerprinting.

Used to compare retrieval runs across environments without persisting raw queries
or scope identifiers (tenant/dataset/document ids).
"""

import json
from typing import Any

from app.rag.core.filters import summarize_metadata_filter
from app.rag.core.hashing import stable_hash

_BANNED_KEYS = {
    # Text-like (potential PII / content leakage)
    "question",
    "query",
    "query_for_retrieval",
    "history",
    # Scope identifiers (high-cardinality; potential leakage)
    "tenant_id",
    "account_id",
    "dataset_id",
    "document_ids",
    # Filters can embed identifiers / PII-like values
    "metadata_filter",
}


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return _normalize_mapping(value)
    if isinstance(value, (list, tuple, set)):
        return _normalize_sequence(value)

    # Best-effort: keep the fingerprint deterministic across processes.
    return str(value)


def _normalize_mapping(value: dict[Any, Any]) -> dict[str, Any] | None:
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
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
    raw = config if isinstance(config, dict) else {}
    cleaned = _normalize_value(raw)
    cleaned = cleaned if isinstance(cleaned, dict) else {}
    metadata_filter = raw.get("metadata_filter")
    if isinstance(metadata_filter, dict) and metadata_filter:
        metadata_payload = json.dumps(
            metadata_filter, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
        )
        cleaned["metadata_filter_hash"] = stable_hash(metadata_payload, length=32)
        metadata_summary = summarize_metadata_filter(metadata_filter)
        if metadata_summary:
            cleaned["metadata_filter_summary"] = metadata_summary

    payload = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = stable_hash(payload, length=32)
    return {
        "schema": str(schema or "").strip() or "mimirq.retrieval_config.v1",
        "hash": digest,
        "config": cleaned,
    }


__all__ = ["build_retrieval_config_fingerprint"]
