"""Merge/split resolution undo helpers for the KG API routes.

Split out of ``app.rag.kg.api.routes`` (see ``app.rag.kg.api.routes_support``).
The undo route itself stays in the routes module. Function-local (deferred)
imports are preserved verbatim.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.kg.api.routes_support.common import KG_API_FALLBACK_LOG_MESSAGE, logger
from app.rag.kg.api.routes_support.projection import _dict_list, _uuid_list, _uuid_or_none
from app.rag.kg.api.routes_support.schemas import KGUndoStats


def _get_applied_resolution_action(db: Session, action_model: Any, *, tenant_id: UUID, action_id: UUID) -> Any:
    action = db.query(action_model).filter_by(tenant_id=tenant_id, id=action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Resolution action not found")
    if str(getattr(action, "status", "") or "").strip().lower() != "applied":
        raise HTTPException(status_code=409, detail="Resolution action is not in applied state")
    return action


def _resolution_action_kind(payload: dict[str, Any]) -> str:
    action_kind = str(payload.get("action") or "").strip().lower()
    if action_kind not in {"merge", "split"}:
        raise HTTPException(status_code=400, detail="Unsupported resolution action for undo")
    return action_kind


def _restore_updated_assocs(db: Session, event_entity_model: Any, *, entity_id: UUID, assoc_ids: set[str]) -> int:
    restored = 0
    if not assoc_ids:
        return restored
    for assoc in db.query(event_entity_model).all():
        assoc_id = str(getattr(assoc, "id", "") or "")
        if assoc_id and assoc_id in assoc_ids:
            assoc.entity_id = entity_id
            restored += 1
    return restored


def _restore_deleted_assoc_rows(db: Session, event_entity_model: Any, *, source_id: UUID, rows: list[dict[str, Any]]) -> int:
    restored = 0
    for row in rows:
        row_id = _uuid_or_none(row.get("id"))
        event_id = _uuid_or_none(row.get("event_id"))
        if row_id is None or event_id is None:
            continue
        db.add(
            event_entity_model(
                id=row_id,
                event_id=event_id,
                entity_id=source_id,
                weight=float(row.get("weight", 1.0) or 1.0),
                role=(str(row.get("role")) if row.get("role") is not None else None),
                extra_data=(row.get("extra_data") if isinstance(row.get("extra_data"), dict) else None),
            )
        )
        restored += 1
    return restored


def _restore_updated_relations(
    db: Session,
    relation_model: Any,
    *,
    tenant_id: UUID,
    source_id: UUID,
    target_id: UUID,
    relation_ids: set[str],
) -> int:
    restored = 0
    if not relation_ids:
        return restored
    for relation in db.query(relation_model).filter_by(tenant_id=tenant_id).all():
        relation_id = str(getattr(relation, "id", "") or "")
        if not relation_id or relation_id not in relation_ids:
            continue
        if getattr(relation, "subject_entity_id", None) == target_id:
            relation.subject_entity_id = source_id
        if getattr(relation, "object_entity_id", None) == target_id:
            relation.object_entity_id = source_id
        restored += 1
    return restored


def _limited_optional_str(value: Any, limit: int) -> str | None:
    return str(value)[:limit] if value else None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _restored_relation_row_payload(*, row: dict[str, Any], tenant_id: UUID, source_id: UUID) -> dict[str, Any]:
    now = datetime.now(UTC).replace(tzinfo=None)
    return {
        "id": _uuid_or_none(row.get("id")),
        "tenant_id": tenant_id,
        "pipeline_hash": _limited_optional_str(row.get("pipeline_hash"), 200),
        "document_id": _uuid_or_none(row.get("document_id")),
        "chunk_id": _uuid_or_none(row.get("chunk_id")),
        "event_id": _uuid_or_none(row.get("event_id")),
        "subject_entity_id": _uuid_or_none(row.get("subject_entity_id")) or source_id,
        "predicate": str(row.get("predicate") or "").strip() or "related_to",
        "predicate_raw": _limited_optional_str(row.get("predicate_raw"), 200),
        "object_entity_id": _uuid_or_none(row.get("object_entity_id")) or source_id,
        "confidence": float(row.get("confidence", 0.5) or 0.5),
        "qualifiers": _dict_or_none(row.get("qualifiers")),
        "references": _dict_or_none(row.get("references")),
        "extra_data": _dict_or_none(row.get("extra_data")),
        "created_at": now,
        "updated_at": now,
    }


def _restore_deleted_relation_rows(
    db: Session,
    relation_model: Any,
    *,
    tenant_id: UUID,
    source_id: UUID,
    rows: list[dict[str, Any]],
) -> int:
    restored = 0
    for row in rows:
        relation_id = _uuid_or_none(row.get("id"))
        if relation_id is None:
            continue
        payload = _restored_relation_row_payload(row=row, tenant_id=tenant_id, source_id=source_id)
        db.add(relation_model(**payload))
        restored += 1
    return restored


def _remove_merge_redirect(
    db: Session,
    redirect_model: Any,
    *,
    tenant_id: UUID,
    source_id: UUID,
    target_id: UUID,
    redirect_created: bool,
) -> bool:
    if not redirect_created:
        return False
    row = db.query(redirect_model).filter_by(tenant_id=tenant_id, from_entity_id=source_id).first()
    if row and getattr(row, "to_entity_id", None) == target_id:
        db.delete(row)
        return True
    return False


def _restore_source_entity_vector_if_needed(db: Session, *, tenant_id: UUID, source_id: UUID, vector_deleted: bool) -> None:
    if not vector_deleted or not bool(getattr(settings, "KG_ENTITY_RESOLUTION_UPDATE_VECTORS_ENABLED", False)):
        return
    try:
        from app.rag.kg.models import KgEntity  # noqa: WPS433
        from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name  # noqa: WPS433

        ent = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=source_id).first()
        if ent is None or not getattr(ent, "vector", None):
            return
        collection = resolve_collection_name("kg_entities")
        milvus = get_milvus_adapter(collection_name=collection, vector_field="embedding")
        milvus.add_vectors(
            items=[
                {
                    "id": str(source_id),
                    "content": str(getattr(ent, "name", "") or ""),
                    "metadata": {
                        "name": str(getattr(ent, "name", "") or ""),
                        "normalized_name": str(getattr(ent, "normalized_name", "") or ""),
                        "tenant_id": str(tenant_id),
                        "type": str(getattr(ent, "type", "") or "unknown"),
                        "description": str(getattr(ent, "description", "") or ""),
                        "index_kind": "entity",
                    },
                }
            ],
            embeddings=[list(ent.vector)],
        )
    except Exception as exc:
        logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)


def _undo_merge_resolution_action(
    db: Session,
    *,
    tenant_id: UUID,
    payload: dict[str, Any],
    redirect_model: Any,
    event_entity_model: Any,
    relation_model: Any,
) -> KGUndoStats:
    source_id = _uuid_or_none(payload.get("source_entity_id"))
    target_id = _uuid_or_none(payload.get("target_entity_id"))
    if source_id is None or target_id is None:
        raise HTTPException(status_code=400, detail="Invalid action payload (missing entity ids)")

    stats = KGUndoStats(source_id=source_id, target_id=target_id)
    stats.restored_edges += _restore_updated_assocs(
        db,
        event_entity_model,
        entity_id=source_id,
        assoc_ids={str(item) for item in _uuid_list(payload.get("event_entity_updated_ids")) if item},
    )
    stats.restored_edges += _restore_deleted_assoc_rows(
        db,
        event_entity_model,
        source_id=source_id,
        rows=_dict_list(payload.get("event_entity_deleted_rows")),
    )
    stats.restored_relations += _restore_updated_relations(
        db,
        relation_model,
        tenant_id=tenant_id,
        source_id=source_id,
        target_id=target_id,
        relation_ids={str(item) for item in _uuid_list(payload.get("relation_updated_ids")) if item},
    )
    stats.restored_relations += _restore_deleted_relation_rows(
        db,
        relation_model,
        tenant_id=tenant_id,
        source_id=source_id,
        rows=_dict_list(payload.get("relation_deleted_rows")),
    )
    stats.redirect_removed = _remove_merge_redirect(
        db,
        redirect_model,
        tenant_id=tenant_id,
        source_id=source_id,
        target_id=target_id,
        redirect_created=bool(payload.get("redirect_created", False)),
    )
    _restore_source_entity_vector_if_needed(
        db,
        tenant_id=tenant_id,
        source_id=source_id,
        vector_deleted=bool(payload.get("vector_deleted", False)),
    )
    return stats


def _undo_split_resolution_action(
    db: Session,
    *,
    tenant_id: UUID,
    payload: dict[str, Any],
    redirect_model: Any,
    event_entity_model: Any,
    relation_model: Any,
) -> KGUndoStats:
    original_id = _uuid_or_none(payload.get("original_entity_id"))
    new_id = _uuid_or_none(payload.get("new_entity_id"))
    if original_id is None or new_id is None:
        raise HTTPException(status_code=400, detail="Invalid action payload (missing entity ids)")

    stats = KGUndoStats(source_id=original_id, target_id=new_id)
    stats.restored_edges += _restore_updated_assocs(
        db,
        event_entity_model,
        entity_id=original_id,
        assoc_ids={str(item) for item in (payload.get("moved_event_entity_ids") or []) if str(item or "").strip()},
    )
    stats.restored_relations += _restore_split_relations(
        db,
        relation_model,
        tenant_id=tenant_id,
        original_id=original_id,
        new_id=new_id,
        moved_relation_ids={str(item) for item in (payload.get("moved_relation_ids") or []) if str(item or "").strip()},
    )
    stats.deleted_new_entity = _delete_orphan_split_entity(
        db,
        redirect_model=redirect_model,
        event_entity_model=event_entity_model,
        relation_model=relation_model,
        tenant_id=tenant_id,
        new_id=new_id,
    )
    return stats


def _restore_split_relations(
    db: Session,
    relation_model: Any,
    *,
    tenant_id: UUID,
    original_id: UUID,
    new_id: UUID,
    moved_relation_ids: set[str],
) -> int:
    restored = 0
    if not moved_relation_ids:
        return restored
    for relation in db.query(relation_model).filter_by(tenant_id=tenant_id).all():
        relation_id = str(getattr(relation, "id", "") or "")
        if not relation_id or relation_id not in moved_relation_ids:
            continue
        if getattr(relation, "subject_entity_id", None) == new_id:
            relation.subject_entity_id = original_id
        if getattr(relation, "object_entity_id", None) == new_id:
            relation.object_entity_id = original_id
        restored += 1
    return restored


def _delete_orphan_split_entity(
    db: Session,
    *,
    redirect_model: Any,
    event_entity_model: Any,
    relation_model: Any,
    tenant_id: UUID,
    new_id: UUID,
) -> bool:
    try:
        from app.rag.kg.models import KgEntity, KgEntityAlias  # noqa: WPS433

        has_refs = any(
            [
                db.query(event_entity_model).filter_by(entity_id=new_id).all(),
                db.query(relation_model).filter_by(tenant_id=tenant_id, subject_entity_id=new_id).all(),
                db.query(relation_model).filter_by(tenant_id=tenant_id, object_entity_id=new_id).all(),
                db.query(KgEntityAlias).filter_by(tenant_id=tenant_id, canonical_entity_id=new_id).all(),
                db.query(redirect_model).filter_by(tenant_id=tenant_id, from_entity_id=new_id).all(),
                db.query(redirect_model).filter_by(tenant_id=tenant_id, to_entity_id=new_id).all(),
            ]
        )
        if has_refs:
            return False
        entity = db.query(KgEntity).filter_by(tenant_id=tenant_id, id=new_id).first()
        if entity is None:
            return False
        db.delete(entity)
        return True
    except Exception as exc:
        logger.debug(KG_API_FALLBACK_LOG_MESSAGE, exc)
        return False
