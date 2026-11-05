"""Dify citation records rules and operations."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.rag.core.logging import get_logger
from app.services.dify_integration import answer_hints, chunk_hydration, query_policy
from app.services.dify_integration.anchor_strength import (
    _record_matches_requested_slot as _record_matches_requested_slot,
)
from app.services.dify_integration.common import _CONTENT_KEYS, _METADATA_KEYS, _TITLE_KEYS
from app.services.dify_integration.common import _citation_chunk_id as _citation_chunk_id
from app.services.dify_integration.common import _citation_dataset_id as _citation_dataset_id
from app.services.dify_integration.common import _citation_score as _citation_score
from app.services.dify_integration.common import _first_non_empty as _first_non_empty

logger = get_logger(__name__)


def _citation_needs_slot_content_hydration(
    citation: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    content = _first_non_empty(citation, _CONTENT_KEYS)
    if not content:
        return True
    if "..." not in content and "…" not in content:
        return False
    requested_slots = query_policy._requested_policy_slot_specs_for_query(
        query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if not requested_slots:
        return False
    record = {
        "content": content,
        "title": _first_non_empty(citation, _TITLE_KEYS),
        "metadata": dict(citation.get("metadata") or {}) if isinstance(citation.get("metadata"), dict) else {},
    }
    return _record_matches_requested_slot(record, requested_slots)


def _records_from_citations(
    *,
    db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
    fallback_dataset_id: UUID | None,
    query: str,
    hydration_query: str | None = None,
    policy_plugin_refs: tuple[str, ...] = (),
    hydrated_chunk_content_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    slot_hydration_query = hydration_query or query
    citations_needing_hydration = [
        citation
        for citation in citations or []
        if _citation_needs_slot_content_hydration(
            citation,
            query=slot_hydration_query,
            policy_plugin_refs=policy_plugin_refs,
        )
    ]
    if hydrated_chunk_content_map is None:
        chunk_content_map = (
            chunk_hydration._load_chunk_content_map(db=db, tenant_id=tenant_id, citations=citations_needing_hydration)
            if citations_needing_hydration
            else {}
        )
    else:
        chunk_content_map = hydrated_chunk_content_map
    records: list[dict[str, Any]] = []
    for citation in citations:
        chunk_id = _citation_chunk_id(citation)
        if chunk_id and chunk_content_map.get(chunk_id) and citation in citations_needing_hydration:
            citation = {**citation, "content": chunk_content_map[chunk_id]}
        record = _citation_to_dify_record(
            citation,
            dataset_id=fallback_dataset_id,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if record["content"].strip():
            records.append(record)
    return records


async def _records_from_citations_with_managed_hydration(
    *,
    db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
    fallback_dataset_id: UUID | None,
    query: str,
    hydration_query: str | None = None,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    slot_hydration_query = hydration_query or query
    citations_needing_hydration = [
        citation
        for citation in citations or []
        if _citation_needs_slot_content_hydration(
            citation,
            query=slot_hydration_query,
            policy_plugin_refs=policy_plugin_refs,
        )
    ]
    chunk_content_map: dict[str, str] = {}
    if citations_needing_hydration:
        try:
            chunk_content_map = await chunk_hydration._offload_chunk_content_hydration(
                request_db=db,
                tenant_id=tenant_id,
                citations=citations_needing_hydration,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to hydrate Dify chunk content; falling back to citation snippets", exc_info=True)

    return _records_from_citations(
        db=db,
        tenant_id=tenant_id,
        citations=citations,
        fallback_dataset_id=fallback_dataset_id,
        query=query,
        hydration_query=hydration_query,
        policy_plugin_refs=policy_plugin_refs,
        hydrated_chunk_content_map=chunk_content_map,
    )


def _citation_to_dify_record(
    citation: dict[str, Any],
    *,
    dataset_id: UUID | None,
    query: str = "",
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    content = _first_non_empty(citation, _CONTENT_KEYS)
    title = _first_non_empty(citation, _TITLE_KEYS) or "Untitled"

    raw_metadata = citation.get("metadata")
    metadata: dict[str, Any] = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    resolved_dataset_id = _citation_dataset_id(citation, fallback_dataset_id=dataset_id)
    if resolved_dataset_id is not None:
        metadata["dataset_id"] = str(resolved_dataset_id)
    for key in _METADATA_KEYS:
        value = citation.get(key)
        if value is not None and value != "":
            metadata[key] = value
    content = answer_hints._content_with_answer_hints(
        content, metadata, query=query, policy_plugin_refs=policy_plugin_refs
    )

    return {
        "content": content,
        "score": _citation_score(citation),
        "title": title,
        "metadata": metadata,
    }
