"""Dify record identity, deduplication and source value adapters."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.services.dify.common import _first_nonempty_str
from app.services.dify.scoring import _record_source_identity_key


def _record_dedupe_key(record: dict[str, Any]) -> tuple[str | None, str | None, str]:
    source_identity = _record_source_identity_key(record)
    if source_identity:
        return ("source_record", source_identity, "")

    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    chunk_id = _first_nonempty_str(metadata.get("chunk_id"))
    document_id = _first_nonempty_str(metadata.get("document_id"))
    content = record["content"].strip()
    title = record["title"].strip()
    return (chunk_id, document_id, content or title)


def _tag_mixed_intent_records(records: list[dict[str, Any]], *, subquery: str) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for record in records:
        metadata = dict(record.get("metadata") if isinstance(record.get("metadata"), dict) else {})
        metadata["dify_mixed_intent_subquery"] = subquery
        tagged.append({**record, "metadata": metadata})
    return tagged


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping.get(key, default)
    return getattr(row, key, default)


def _coerce_uuid_text(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        return ""


def dedupe_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    record_dedupe_key: Callable[[dict[str, Any]], tuple[str, str, str]],
    record_rank_score: Callable[[dict[str, Any], str, tuple[str, ...]], float],
) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        key = record_dedupe_key(record)
        if not any(key):
            continue
        current = best_by_key.get(key)
        if current is None or record_rank_score(record, query, policy_plugin_refs) > record_rank_score(
            current,
            query,
            policy_plugin_refs,
        ):
            best_by_key[key] = record
    return list(best_by_key.values())
