"""Record dedupe and construction helpers for the Dify adapter.

Mechanically extracted from `app.api.v1.integrations_dify`; do not import that
module from here (see package docstring).
"""

from typing import Any
from uuid import UUID

from app.api.v1.dify_support.scoring import _record_source_identity_key


def _record_dedupe_key(record: dict[str, Any]) -> tuple[str, str, str]:
    source_identity = _record_source_identity_key(record)
    if source_identity:
        return ("source_record", source_identity, "")

    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    chunk_id = str(metadata.get("chunk_id") or "").strip()
    document_id = str(metadata.get("document_id") or "").strip()
    content = str(record.get("content") or "").strip()
    title = str(record.get("title") or "").strip()
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
