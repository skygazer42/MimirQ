"""
Pipeline version helpers.

These are small, testable utilities used by API handlers to resolve the active
pipeline version (`pipeline_hash`) and the derived `doc_pipeline_key` that ties
chunks/vectors/BM25 entries to a specific processing configuration.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID


def get_active_pipeline_hash(doc_metadata: Mapping[str, Any] | None) -> str | None:
    """
    Return the active pipeline hash for a document.

    Priority:
    1) metadata.active_pipeline_hash
    2) metadata.pipeline_hash (legacy/current pipeline hash)
    """
    meta = {} if doc_metadata is None else doc_metadata
    active = meta.get("active_pipeline_hash")
    if active is not None:
        active = active.strip()
        if active:
            return active
    pipeline_hash = meta.get("pipeline_hash")
    if pipeline_hash is None:
        return None
    value = pipeline_hash.strip()
    return value if value else None


def get_selected_pipeline_hash(doc_metadata: Mapping[str, Any] | None, pipeline_hash: str | None) -> str | None:
    """
    Resolve which pipeline hash should be used for reads:
    - explicit pipeline_hash param wins
    - otherwise fallback to active pipeline hash
    """
    explicit = pipeline_hash.strip() if pipeline_hash is not None else None
    if explicit:
        return explicit
    return get_active_pipeline_hash(doc_metadata)


def should_preserve_existing_versions(doc_metadata: Mapping[str, Any] | None) -> bool:
    """
    Return True when a document already has an "active" completed pipeline version,
    and the current `pipeline_hash` points at a different (in-progress) version.

    This is used to avoid clobbering active-version stats/indexes during retries.
    """
    meta = {} if doc_metadata is None else doc_metadata
    if not meta.get("active_pipeline_ready"):
        return False
    active_hash = meta.get("active_pipeline_hash")
    current_hash = meta.get("pipeline_hash")
    if active_hash is not None:
        active_hash = active_hash.strip()
    if current_hash is not None:
        current_hash = current_hash.strip()
    if not active_hash or not current_hash:
        return False
    return active_hash != current_hash


def build_doc_pipeline_key(document_id: UUID, pipeline_hash: str) -> str:
    """Build a stable doc_pipeline_key for a document version."""
    return f"{document_id}:{pipeline_hash}"


def resolve_doc_pipeline_key(
    document_id: UUID,
    doc_metadata: Mapping[str, Any] | None,
    pipeline_hash: str | None,
    *,
    all_versions: bool,
) -> str | None:
    """
    Best-effort helper used by chunk endpoints.

    Returns:
    - doc_pipeline_key string when version scoping is enabled
    - None when `all_versions=true` or no pipeline hash can be resolved
    """
    if all_versions:
        return None
    selected = get_selected_pipeline_hash(doc_metadata, pipeline_hash)
    if not selected:
        return None
    return build_doc_pipeline_key(document_id, selected)
