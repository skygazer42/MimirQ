"""Entity merge / alias suggestion helpers for the KG API routes.

Split out of ``app.rag.kg.api.routes`` (see ``app.rag.kg.api.routes_support``).
Function-local (deferred) imports are preserved verbatim.
"""

import contextlib
import uuid
from datetime import UTC
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.kg.api.routes_support.common import KG_API_FALLBACK_LOG_MESSAGE, KG_ENTITY_NOT_FOUND_DETAIL, logger
from app.rag.kg.api.routes_support.projection import (
    _event_entity_snapshot,
    _relation_snapshot,
    _resolve_entity_id_via_redirects,
    _uuid_or_none,
)
from app.rag.kg.api.routes_support.schemas import KGMergeAffectedRows, KGMergeTargets
from app.rag.kg.schemas import KGEntityAliasSuggestionItem, KGEntityAliasSuggestionsResponse


def _offline_alias_suggestions(
    db: Session,
    entity_model: Any,
    *,
    tenant_id: UUID,
    entity: Any,
    resolved_id: UUID,
    want_k: int,
    min_similarity: float,
) -> KGEntityAliasSuggestionsResponse:
    from sqlalchemy import and_  # noqa: WPS433

    norm = str(getattr(entity, "normalized_name", "") or "").strip()
    prefix = norm[:4] if len(norm) >= 4 else norm
    query = db.query(entity_model).filter(
        and_(
            entity_model.tenant_id == tenant_id,
            entity_model.type == getattr(entity, "type", None),
            entity_model.id != resolved_id,
        )
    )
    if prefix:
        query = query.filter(entity_model.normalized_name.like(f"{prefix}%"))  # noqa: WPS323
    candidates = query.order_by(entity_model.normalized_name.asc(), entity_model.id.asc()).limit(500).all()
    scored = _score_alias_candidates(candidates, norm=norm, min_similarity=float(min_similarity))
    suggestions = [
        _alias_suggestion_item(candidate, similarity=sim, reason="offline:normalized_name_sequence_match")
        for sim, _sid, candidate in scored[:want_k]
    ]
    return KGEntityAliasSuggestionsResponse(
        entity_id=resolved_id,
        suggestions=suggestions,
        mode="offline",
        stats={"candidates": len(candidates), "returned": len(suggestions), "prefix": prefix},
    )


def _score_alias_candidates(candidates: list[Any], *, norm: str, min_similarity: float) -> list[tuple[float, str, Any]]:
    from difflib import SequenceMatcher

    scored: list[tuple[float, str, Any]] = []
    for candidate in candidates:
        candidate_norm = str(getattr(candidate, "normalized_name", "") or "").strip()
        if not candidate_norm:
            continue
        sim = float(SequenceMatcher(a=norm, b=candidate_norm).ratio())
        if sim >= float(min_similarity):
            scored.append((sim, str(candidate.id), candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored


def _alias_suggestion_item(candidate: Any, *, similarity: float, reason: str) -> KGEntityAliasSuggestionItem:
    return KGEntityAliasSuggestionItem(
        entity_id=candidate.id,
        name=str(getattr(candidate, "name", "") or ""),
        type=str(getattr(candidate, "type", "") or "unknown"),
        similarity=float(similarity),
        reason=reason,
    )


def _vector_alias_suggestions(
    db: Session,
    *,
    tenant_id: UUID,
    entity: Any,
    resolved_id: UUID,
    want_k: int,
) -> KGEntityAliasSuggestionsResponse:
    try:
        from app.rag.kg.repository import EntityRepository  # noqa: WPS433

        repo = EntityRepository(db)
        hits = repo.search_similar(
            query_vector=list(entity.vector),
            tenant_id=tenant_id,
            k=max(1, int(want_k)),
            entity_type=str(getattr(entity, "type", "") or None) or None,
        )
        suggestions = [
            _vector_alias_suggestion_item(hit)
            for hit in hits
            if _uuid_or_none(hit.get("entity_id") or hit.get("id")) != resolved_id
        ]
        suggestions = [item for item in suggestions if item is not None][:want_k]
        return KGEntityAliasSuggestionsResponse(
            entity_id=resolved_id, suggestions=suggestions, mode="vector", stats={"returned": len(suggestions)}
        )
    except Exception:
        return KGEntityAliasSuggestionsResponse(
            entity_id=resolved_id,
            suggestions=[],
            mode="vector",
            stats={"returned": 0, "reason": "vector_mode_failed"},
        )


def _vector_alias_suggestion_item(hit: dict[str, Any]) -> KGEntityAliasSuggestionItem | None:
    entity_id = _uuid_or_none(hit.get("entity_id") or hit.get("id"))
    if entity_id is None:
        return None
    return KGEntityAliasSuggestionItem(
        entity_id=entity_id,
        name=str(hit.get("name") or ""),
        type=str(hit.get("type") or "unknown"),
        similarity=float(hit.get("similarity", 0.0) or 0.0),
        reason="vector:milvus_similarity",
    )


def _entity_relation_rows(db: Session, relation_model: Any, *, tenant_id: UUID, entity_id: UUID) -> list[Any]:
    rel_rows = []
    rel_rows.extend(db.query(relation_model).filter_by(tenant_id=tenant_id, subject_entity_id=entity_id).all())
    rel_rows.extend(db.query(relation_model).filter_by(tenant_id=tenant_id, object_entity_id=entity_id).all())
    rel_by_id: dict[str, Any] = {}
    for relation in rel_rows:
        relation_id = str(getattr(relation, "id", "") or "")
        if relation_id:
            rel_by_id[relation_id] = relation
    return list(rel_by_id.values())


def _merge_targets(
    db: Session,
    entity_model: Any,
    *,
    tenant_id: UUID,
    source_raw: UUID,
    target_raw: UUID,
) -> KGMergeTargets:
    if source_raw == target_raw:
        raise HTTPException(status_code=400, detail="source_entity_id must differ from target_entity_id")

    source_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=source_raw)
    target_id = _resolve_entity_id_via_redirects(db=db, tenant_id=tenant_id, entity_id=target_raw)
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Entities already resolve to the same canonical id")

    source_ent = db.query(entity_model).filter_by(tenant_id=tenant_id, id=source_id).first()
    target_ent = db.query(entity_model).filter_by(tenant_id=tenant_id, id=target_id).first()
    if not source_ent or not target_ent:
        raise HTTPException(status_code=404, detail=KG_ENTITY_NOT_FOUND_DETAIL)
    if str(getattr(source_ent, "type", "") or "").strip() != str(getattr(target_ent, "type", "") or "").strip():
        raise HTTPException(status_code=400, detail="Cannot merge entities of different types")
    return KGMergeTargets(source_id=source_id, target_id=target_id, source_entity=source_ent, target_entity=target_ent)


def _merge_affected_rows(
    db: Session,
    *,
    tenant_id: UUID,
    source_id: UUID,
    event_entity_model: Any,
    relation_model: Any,
) -> KGMergeAffectedRows:
    source_assocs = db.query(event_entity_model).filter_by(entity_id=source_id).all()
    source_relations = _entity_relation_rows(db, relation_model, tenant_id=tenant_id, entity_id=source_id)
    return KGMergeAffectedRows(
        source_assocs=source_assocs,
        source_assoc_ids={str(getattr(assoc, "id", "")) for assoc in source_assocs if getattr(assoc, "id", None)},
        assoc_snapshot_by_id={
            str(assoc.id): _event_entity_snapshot(assoc) for assoc in source_assocs if getattr(assoc, "id", None)
        },
        impacted_event_ids={
            getattr(assoc, "event_id", None) for assoc in source_assocs if getattr(assoc, "event_id", None) is not None
        },
        source_relations=source_relations,
        source_relation_ids={
            str(getattr(relation, "id", "")) for relation in source_relations if getattr(relation, "id", None)
        },
        relation_snapshot_by_id={
            str(relation.id): _relation_snapshot(relation)
            for relation in source_relations
            if getattr(relation, "id", None)
        },
    )


def _create_merge_action(
    action_model: Any,
    *,
    tenant_id: UUID,
    account_id: str,
    targets: KGMergeTargets,
    affected: KGMergeAffectedRows,
) -> Any:
    from datetime import datetime

    return action_model(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        actor_id=str(account_id or "").strip() or None,
        action_type="merge",
        status="applied",
        payload={
            "version": 1,
            "action": "merge",
            "source_entity_id": str(targets.source_id),
            "target_entity_id": str(targets.target_id),
            "event_entity_updated_ids": sorted([sid for sid in affected.source_assoc_ids if sid]),
            "relation_updated_ids": sorted([sid for sid in affected.source_relation_ids if sid]),
            "event_entity_deleted_rows": [],
            "relation_deleted_rows": [],
            "redirect_created": False,
            "vector_deleted": False,
        },
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _add_resolution_audit_log(
    db: Session,
    audit_log_model: Any,
    *,
    tenant_id: UUID,
    account_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
) -> None:
    try:
        db.add(
            audit_log_model(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_id=str(account_id or "").strip() or None,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
            )
        )
    except Exception as exc:
        logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)


def _ensure_merge_redirect(
    db: Session,
    redirect_model: Any,
    *,
    tenant_id: UUID,
    account_id: str,
    source_id: UUID,
    target_id: UUID,
    action_id: UUID,
) -> bool:
    from datetime import datetime

    existing_redirect = db.query(redirect_model).filter_by(tenant_id=tenant_id, from_entity_id=source_id).first()
    if existing_redirect:
        if getattr(existing_redirect, "to_entity_id", None) != target_id:
            raise HTTPException(status_code=409, detail="Entity redirect already exists to a different canonical id")
        return False
    db.add(
        redirect_model(
            from_entity_id=source_id,
            tenant_id=tenant_id,
            to_entity_id=target_id,
            action_id=action_id,
            created_by=str(account_id or "").strip() or None,
            extra_data={"reason": "merge"},
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    return True


def _apply_merge_relation_updates(
    *, source_id: UUID, target_id: UUID, affected: KGMergeAffectedRows, db: Session
) -> list[dict[str, Any]]:
    relation_deleted_rows: list[dict[str, Any]] = []
    for relation in affected.source_relations:
        relation_id = str(getattr(relation, "id", "") or "")
        if getattr(relation, "subject_entity_id", None) == source_id:
            relation.subject_entity_id = target_id
        if getattr(relation, "object_entity_id", None) == source_id:
            relation.object_entity_id = target_id
        if getattr(relation, "subject_entity_id", None) == getattr(relation, "object_entity_id", None):
            if relation_id and relation_id in affected.relation_snapshot_by_id:
                relation_deleted_rows.append(affected.relation_snapshot_by_id[relation_id])
            db.delete(relation)
    return relation_deleted_rows


def _dedupe_merged_event_entity_edges(
    db: Session,
    event_entity_model: Any,
    *,
    source_id: UUID,
    target_id: UUID,
    affected: KGMergeAffectedRows,
) -> list[dict[str, Any]]:
    if not affected.impacted_event_ids:
        return []
    current_target_assocs = db.query(event_entity_model).filter_by(entity_id=target_id).all()
    by_event: dict[UUID, list[Any]] = {}
    for assoc in current_target_assocs:
        event_id = getattr(assoc, "event_id", None)
        if event_id is not None and event_id in affected.impacted_event_ids:
            by_event.setdefault(event_id, []).append(assoc)
    return _delete_duplicate_target_assocs(db, source_id=source_id, affected=affected, by_event=by_event)


def _delete_duplicate_target_assocs(
    db: Session,
    *,
    source_id: UUID,
    affected: KGMergeAffectedRows,
    by_event: dict[UUID, list[Any]],
) -> list[dict[str, Any]]:
    deleted_assoc_rows: list[dict[str, Any]] = []
    for rows in by_event.values():
        if len(rows) <= 1:
            continue
        keep = _target_assoc_to_keep(rows, affected.source_assoc_ids)
        _merge_duplicate_assoc_fields(keep, rows)
        for row in rows:
            row_id = str(getattr(row, "id", "") or "")
            if row is keep or row_id not in affected.source_assoc_ids:
                continue
            snapshot = affected.assoc_snapshot_by_id.get(row_id) or _event_entity_snapshot(row)
            snapshot["entity_id"] = str(source_id)
            deleted_assoc_rows.append(snapshot)
            db.delete(row)
    return deleted_assoc_rows


def _target_assoc_to_keep(rows: list[Any], source_assoc_ids: set[str]) -> Any:
    for row in rows:
        row_id = str(getattr(row, "id", "") or "")
        if row_id and row_id not in source_assoc_ids:
            return row
    return rows[0]


def _merge_duplicate_assoc_fields(keep: Any, rows: list[Any]) -> None:
    keep_weight = float(getattr(keep, "weight", 1.0) or 1.0)
    keep_role = getattr(keep, "role", None)
    keep_extra = getattr(keep, "extra_data", None)
    for row in rows:
        if row is keep:
            continue
        keep_weight = max(keep_weight, float(getattr(row, "weight", 1.0) or 1.0))
        if not keep_role:
            keep_role = getattr(row, "role", None)
        if not keep_extra:
            keep_extra = getattr(row, "extra_data", None)
    keep.weight = keep_weight
    keep.role = keep_role
    keep.extra_data = keep_extra


def _delete_source_entity_vector_if_enabled(source_id: UUID) -> bool:
    if not bool(getattr(settings, "KG_ENTITY_RESOLUTION_UPDATE_VECTORS_ENABLED", False)):
        return False
    try:
        from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name  # noqa: WPS433

        collection = resolve_collection_name("kg_entities")
        milvus = get_milvus_adapter(collection_name=collection, vector_field="embedding")
        milvus.delete([str(source_id)])
        return True
    except Exception:
        return False


def _commit_or_rollback(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        raise
