"""Owned events operations for indexing."""

import logging
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.models.document import Document as DBDocument
from app.rag.kg.models import KgEntity, KgEventEntity, KgRelation, KgSourceEvent
from app.rag.kg.provenance import build_event_entity_provenance
from app.services.document_index_channel_service import (
    DOCUMENT_INDEX_CHANNEL_DISABLED,
    DOCUMENT_INDEX_CHANNEL_ERROR,
    DOCUMENT_INDEX_CHANNEL_PROCESSING,
    DOCUMENT_INDEX_CHANNEL_READY,
    DOCUMENT_INDEX_CHANNEL_SKIPPED,
)
from app.services.indexing.tracking import (
    load_document_for_channel_tracking,
    track_document_channel,
)
from app.services.indexing.vector_writer import _vector_write_batch_size
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name
from app.types.indexing import (
    EventEntityInput,
    EventInput,
    IndexingOptions,
    IndexKind,
    PersistEventsResult,
)

logger = logging.getLogger("indexer")


def _coerce_entity_upsert_input(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    normalized_name = str(raw.get("normalized_name") or name).strip()
    if not normalized_name:
        return None
    return {
        "name": name,
        "normalized_name": normalized_name,
        "type": str(raw.get("type") or "unknown").strip() or "unknown",
        "description": str(raw.get("description")).strip() if isinstance(raw.get("description"), str) else None,
        "vector": raw.get("vector") if isinstance(raw.get("vector"), list) else None,
        "extra_data": raw.get("extra_data") if isinstance(raw.get("extra_data"), dict) else None,
    }


def _enrich_entity_best_effort(
    entity: KgEntity,
    *,
    description: str | None,
    vector: list[Any] | None,
    extra_data: dict[str, Any] | None,
) -> None:
    if description and not entity.description:
        entity.description = description
    if vector and not entity.vector:
        entity.vector = vector
    if extra_data and not entity.extra_data:
        entity.extra_data = extra_data


def _event_references(event: KgSourceEvent) -> dict[str, Any]:
    refs = event.references
    return refs if isinstance(refs, dict) else {}


def _event_pipeline_hash(event: KgSourceEvent, refs: dict[str, Any]) -> str | None:
    pipeline_hash = str(event.pipeline_hash or refs.get("pipeline_hash") or "").strip() or None
    return pipeline_hash[:200] if pipeline_hash and len(pipeline_hash) > 200 else pipeline_hash


def _event_vector_metadata(event: KgSourceEvent, refs: dict[str, Any]) -> dict[str, Any]:
    pipeline_hash = _event_pipeline_hash(event, refs)
    meta: dict[str, Any] = {
        "tenant_id": str(event.tenant_id),
        "document_id": str(event.document_id) if event.document_id else "",
        "chunk_id": str(event.chunk_id) if event.chunk_id else "",
        "title": event.title,
        "summary": event.summary,
        "index_kind": IndexKind.EVENT.value,
    }
    if pipeline_hash:
        meta["pipeline_hash"] = pipeline_hash
        if event.document_id:
            meta["doc_pipeline_key"] = f"{event.document_id}:{pipeline_hash}"
    for key in (
        "chunk_index",
        "page",
        "start_char",
        "end_char",
        "chunk_key",
        "content_hash",
        "content_len",
        "source",
    ):
        value = refs.get(key)
        if value is not None:
            meta[key] = value
    return meta


def _event_vector_item(event: KgSourceEvent) -> tuple[dict[str, Any], list[float]] | None:
    if not event.content_vector:
        return None
    refs = _event_references(event)
    return (
        {
            "id": str(event.id),
            "content": event.content,
            "metadata": _event_vector_metadata(event, refs),
        },
        list(event.content_vector),
    )


class EventIndexer:
    """Own event/entity persistence, vector outcomes, and scoped cleanup."""

    def __init__(self, db: Session) -> None:
        self._db = db
        event_collection = resolve_collection_name("kg_events")
        entity_collection = resolve_collection_name("kg_entities")
        self._event_vector = get_milvus_adapter(collection_name=event_collection, vector_field="embedding")
        self._entity_vector = get_milvus_adapter(collection_name=entity_collection, vector_field="embedding")

    def _resolve_event_vector_enabled(self, options: IndexingOptions | None) -> bool:
        if options and options.event_vector_enabled is not None:
            return bool(options.event_vector_enabled)
        return settings.EVENT_VECTOR_ENABLED

    def _resolve_entity_vector_enabled(self, options: IndexingOptions | None) -> bool:
        if options and options.entity_vector_enabled is not None:
            return bool(options.entity_vector_enabled)
        return settings.ENTITY_VECTOR_ENABLED

    def _tracked_document_for_events(self, *, tenant_id: UUID, events: Sequence[EventInput]) -> DBDocument | None:
        document_ids = {item.document_id for item in events if item.document_id is not None}
        if len(document_ids) != 1:
            return None
        return load_document_for_channel_tracking(self._db, tenant_id=tenant_id, document_id=next(iter(document_ids)))

    def _normalized_event_pipeline_hash(self, refs: dict[str, Any]) -> str | None:
        raw_pipeline_hash = refs.get("pipeline_hash")
        if not isinstance(raw_pipeline_hash, str):
            return None
        pipeline_hash = raw_pipeline_hash.strip() or None
        if pipeline_hash and len(pipeline_hash) > 200:
            return pipeline_hash[:200]
        return pipeline_hash

    def _event_link_extra(self, *, ent: EventEntityInput, link_extra_data: dict[str, Any]) -> dict[str, Any]:
        link_extra = dict(link_extra_data)
        evidence_quote = (ent.evidence_quote or "").strip()
        if evidence_quote:
            link_extra["evidence_quote"] = evidence_quote[:240]
        evidence_source = (ent.evidence_source or "").strip()
        if evidence_source:
            link_extra["evidence_source"] = evidence_source
        for field_name, value in (
            ("evidence_start_char", ent.evidence_start_char),
            ("evidence_end_char", ent.evidence_end_char),
        ):
            if value is not None:
                link_extra[field_name] = value
        return link_extra

    def _entity_for_event(
        self,
        *,
        tenant_id: UUID,
        ent: EventEntityInput,
        entity_cache: dict[tuple[str, str, str], KgEntity],
    ) -> KgEntity | None:
        name = ent.name.strip()
        if not name:
            return None
        normalized = (ent.normalized_name or name.lower()).strip()
        ent_type = (ent.type or "unknown").strip() or "unknown"
        cache_key = (str(tenant_id), normalized, ent_type)
        entity_obj = entity_cache.get(cache_key)
        if entity_obj is None:
            entity_obj = self._get_or_create_entity(
                tenant_id=tenant_id,
                name=name,
                normalized_name=normalized,
                type_=ent_type,
                description=ent.description,
            )
            entity_cache[cache_key] = entity_obj
        if ent.vector and not entity_obj.vector:
            entity_obj.vector = ent.vector
        return entity_obj

    def _materialize_index_events(
        self,
        *,
        tenant_id: UUID,
        events: Sequence[EventInput],
    ) -> tuple[list[KgSourceEvent], dict[tuple[str, str, str], KgEntity]]:
        entity_cache: dict[tuple[str, str, str], KgEntity] = {}
        db_events: list[KgSourceEvent] = []
        for item in events:
            refs = item.references or {}
            event_obj = KgSourceEvent(
                tenant_id=tenant_id,
                pipeline_hash=self._normalized_event_pipeline_hash(refs),
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                title=item.title,
                summary=item.summary,
                content=item.content,
                content_vector=item.vector,
                references=refs or None,
                extra_data=item.extra_data,
            )
            self._db.add(event_obj)
            db_events.append(event_obj)
            link_extra_data = build_event_entity_provenance(
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                references=refs,
            )
            for ent in item.entities:
                entity_obj = self._entity_for_event(tenant_id=tenant_id, ent=ent, entity_cache=entity_cache)
                if entity_obj is None:
                    continue
                self._db.add(
                    KgEventEntity(
                        event=event_obj,
                        entity=entity_obj,
                        weight=1.0,
                        role=ent.role,
                        extra_data=(self._event_link_extra(ent=ent, link_extra_data=link_extra_data) or None),
                    )
                )
        return db_events, entity_cache

    def _track_index_vector_channel(
        self,
        *,
        document: DBDocument | None,
        channel: str,
        enabled: bool,
        items: Sequence[Any],
        candidates: Sequence[Any],
        writer,
        failure_error: str,
        commit: bool,
    ) -> list[str]:
        if not commit:
            return []
        if not enabled:
            track_document_channel(self._db, document=document, channel=channel, status=DOCUMENT_INDEX_CHANNEL_DISABLED)
            return []
        track_document_channel(
            self._db,
            document=document,
            channel=channel,
            status=DOCUMENT_INDEX_CHANNEL_PROCESSING,
            increment_attempt=True,
        )
        if not candidates:
            track_document_channel(self._db, document=document, channel=channel, status=DOCUMENT_INDEX_CHANNEL_SKIPPED)
            return []
        vector_ids = writer(list(items))
        success = len(vector_ids) == len(candidates)
        track_document_channel(
            self._db,
            document=document,
            channel=channel,
            status=DOCUMENT_INDEX_CHANNEL_READY if success else DOCUMENT_INDEX_CHANNEL_ERROR,
            error=None if success else failure_error,
        )
        return vector_ids

    def index(
        self,
        *,
        tenant_id: UUID,
        events: Sequence[EventInput],
        commit: bool = True,
        options: IndexingOptions | None = None,
    ) -> PersistEventsResult:
        if not events:
            return PersistEventsResult(
                events=[],
                entities=[],
                event_ids=[],
                entity_ids=[],
                event_vector_ids=[],
                entity_vector_ids=[],
            )
        db_events, entity_cache = self._materialize_index_events(tenant_id=tenant_id, events=events)
        tracked_document = self._tracked_document_for_events(tenant_id=tenant_id, events=events)
        event_vector_enabled = self._resolve_event_vector_enabled(options)
        entity_vector_enabled = self._resolve_entity_vector_enabled(options)

        if commit:
            self._db.commit()
        else:
            self._db.flush()

        event_vector_ids = self._track_index_vector_channel(
            document=tracked_document,
            channel="event_vector",
            enabled=event_vector_enabled,
            items=db_events,
            candidates=[event for event in db_events if event.content_vector],
            writer=self.write_event_vectors,
            failure_error="event_vector_write_failed",
            commit=commit,
        )
        entity_vector_ids = self._track_index_vector_channel(
            document=tracked_document,
            channel="entity_vector",
            enabled=entity_vector_enabled,
            items=list(entity_cache.values()),
            candidates=[entity for entity in entity_cache.values() if entity.vector],
            writer=self.write_entity_vectors,
            failure_error="entity_vector_write_failed",
            commit=commit,
        )

        return PersistEventsResult(
            events=db_events,
            entities=list(entity_cache.values()),
            event_ids=[ev.id for ev in db_events],
            entity_ids=[ent.id for ent in entity_cache.values()],
            event_vector_ids=event_vector_ids,
            entity_vector_ids=entity_vector_ids,
        )

    def upsert_entities(
        self,
        *,
        tenant_id: UUID,
        entities: Sequence[dict[str, Any]],
        commit: bool = True,
        options: IndexingOptions | None = None,
    ) -> list[KgEntity]:
        """
        Upsert entities without creating events.

        Intended for process knowledge nodes like Skill/SOP entities that should:
        - live in `kg_entities`,
        - be vector-indexed (optional), and
        - be linked to events (handled by caller).
        """
        if not entities:
            return []

        # Keep insertion order stable while deduplicating by (normalized_name, type).
        unique: dict[tuple[str, str], KgEntity] = {}

        for raw in entities:
            item = _coerce_entity_upsert_input(raw)
            if item is None:
                continue
            key = (item["normalized_name"], item["type"])
            ent = unique.get(key)
            if ent is None:
                ent = self._get_or_create_entity(
                    tenant_id=tenant_id,
                    name=item["name"],
                    normalized_name=item["normalized_name"],
                    type_=item["type"],
                    description=item["description"],
                )
                unique[key] = ent

            # Best-effort enrichment (avoid clobbering user edits).
            _enrich_entity_best_effort(
                ent,
                description=item["description"],
                vector=item["vector"],
                extra_data=item["extra_data"],
            )

        out = list(unique.values())
        if not out:
            return []

        if commit:
            self._db.commit()
        else:
            self._db.flush()

        if commit and self._resolve_entity_vector_enabled(options):
            self.write_entity_vectors(out)

        return out

    def delete_event_indexes(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        commit: bool = True,
        prune_orphan_entities: bool = False,
        strict: bool = False,
    ) -> dict[str, int]:
        return self._delete_event_indexes(
            tenant_id=tenant_id,
            query=(
                self._db.query(KgSourceEvent).filter(
                    KgSourceEvent.tenant_id == tenant_id,
                    KgSourceEvent.document_id == document_id,
                )
            ),
            commit=commit,
            prune_orphan_entities=prune_orphan_entities,
            strict=strict,
        )

    def delete_event_indexes_for_chunks(
        self,
        *,
        tenant_id: UUID,
        chunk_ids: Sequence[UUID],
        commit: bool = True,
        exclude_event_ids: Sequence[UUID] | None = None,
        prune_orphan_entities: bool = False,
        strict: bool = False,
    ) -> dict[str, int]:
        """
        Delete KG events (and vectors) for a set of chunk_ids.

        This is primarily used to make KG extraction idempotent when re-running
        on the same chunks (avoid duplicate events).
        """
        if not chunk_ids:
            return {"events_deleted": 0, "entities_pruned": 0}

        query = self._db.query(KgSourceEvent).filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.chunk_id.in_(chunk_ids),
        )
        if exclude_event_ids:
            query = query.filter(~KgSourceEvent.id.in_(exclude_event_ids))

        return self._delete_event_indexes(
            tenant_id=tenant_id,
            query=query,
            commit=commit,
            prune_orphan_entities=prune_orphan_entities,
            strict=strict,
        )

    def _orphan_entity_query(self, *, tenant_id: UUID):
        rel_as_subject = aliased(KgRelation)
        rel_as_object = aliased(KgRelation)
        return (
            self._db.query(KgEntity.id)
            .outerjoin(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
            .outerjoin(rel_as_subject, rel_as_subject.subject_entity_id == KgEntity.id)
            .outerjoin(rel_as_object, rel_as_object.object_entity_id == KgEntity.id)
            .filter(KgEntity.tenant_id == tenant_id)
            .filter(KgEventEntity.entity_id.is_(None))
            .filter(rel_as_subject.id.is_(None))
            .filter(rel_as_object.id.is_(None))
            .distinct()
        )

    def _delete_orphan_entity_batch(self, *, orphan_ids: list[UUID], commit: bool, strict: bool) -> None:
        try:
            try:
                self._entity_vector.delete([str(eid) for eid in orphan_ids])
            except Exception as exc:
                logger.warning("Failed to delete KG entity vectors: %s", exc)
                if strict:
                    raise
            self._db.query(KgEntity).filter(KgEntity.id.in_(orphan_ids)).delete(synchronize_session=False)
            if commit:
                self._db.commit()
            else:
                self._db.flush()
        except Exception:
            if commit:
                self._db.rollback()
            raise

    def prune_orphan_entities(
        self,
        *,
        tenant_id: UUID,
        entity_ids: Sequence[UUID] | None = None,
        commit: bool = True,
        strict: bool = False,
    ) -> int:
        """
        Delete KG entities (and vectors) that have no remaining references.

        When `entity_ids` is provided, pruning is scoped to that candidate set.

        NOTE:
        - Entities can be referenced by multiple KG structures:
          - `kg_event_entities` (event <-> entity)
          - `kg_relations` (entity <-> entity)
        - Once `kg_relations` exists, pruning must consider both, otherwise we can
          delete Skill/SOP nodes or relation-only entities.
        """
        q = self._orphan_entity_query(tenant_id=tenant_id)
        if entity_ids:
            q = q.filter(KgEntity.id.in_(entity_ids))
        batch_size = max(1, _vector_write_batch_size())
        last_entity_id: UUID | None = None
        deleted = 0
        while True:
            batch_query = q
            if last_entity_id is not None:
                batch_query = batch_query.filter(KgEntity.id > last_entity_id)
            batch_query = batch_query.order_by(KgEntity.id).limit(batch_size)
            orphan_ids = [row[0] for row in batch_query.all() if row and row[0]]
            if not orphan_ids:
                break
            self._delete_orphan_entity_batch(orphan_ids=orphan_ids, commit=commit, strict=strict)
            deleted += len(orphan_ids)
            last_entity_id = orphan_ids[-1]

        return deleted

    def _event_batch_ids(self, query: Any, *, last_id: UUID | None, batch_size: int) -> list[UUID]:
        query_ids = query.with_entities(KgSourceEvent.id)
        if last_id is not None:
            query_ids = query_ids.filter(KgSourceEvent.id > last_id)
        query_ids = query_ids.order_by(KgSourceEvent.id).limit(batch_size)
        return [row[0] for row in query_ids.all() if row and row[0]]

    def _candidate_entity_ids_for_events(self, *, event_ids: list[UUID], prune_orphan_entities: bool) -> list[UUID]:
        if not prune_orphan_entities:
            return []
        return [
            row[0]
            for row in (
                self._db.query(KgEventEntity.entity_id).filter(KgEventEntity.event_id.in_(event_ids)).distinct().all()
            )
            if row and row[0]
        ]

    def _delete_event_index_batch(
        self,
        *,
        tenant_id: UUID,
        event_ids: list[UUID],
        candidate_entity_ids: list[UUID],
        commit: bool,
        prune_orphan_entities: bool,
        strict: bool,
    ) -> tuple[int, int]:
        try:
            try:
                self._event_vector.delete([str(ev_id) for ev_id in event_ids])
            except Exception as exc:
                logger.warning("Failed to delete KG event vectors: %s", exc)
                if strict:
                    raise
            batch_deleted = int(
                self._db.query(KgSourceEvent).filter(KgSourceEvent.id.in_(event_ids)).delete(synchronize_session=False)
                or 0
            )
            if commit or candidate_entity_ids:
                self._db.flush()
            batch_pruned = 0
            if prune_orphan_entities and candidate_entity_ids:
                batch_pruned = int(
                    self.prune_orphan_entities(
                        tenant_id=tenant_id,
                        entity_ids=candidate_entity_ids,
                        commit=False,
                        strict=strict,
                    )
                )
            if commit:
                self._db.commit()
            elif not candidate_entity_ids:
                self._db.flush()
            return batch_deleted, batch_pruned
        except Exception:
            if commit:
                self._db.rollback()
            raise

    def _delete_event_indexes(
        self,
        *,
        tenant_id: UUID,
        query,
        commit: bool,
        prune_orphan_entities: bool,
        strict: bool,
    ) -> dict[str, int]:
        batch_size = max(1, _vector_write_batch_size())
        deleted = 0
        pruned = 0
        last_event_id: UUID | None = None

        while True:
            event_ids = self._event_batch_ids(query, last_id=last_event_id, batch_size=batch_size)
            if not event_ids:
                break
            candidate_entity_ids = self._candidate_entity_ids_for_events(
                event_ids=event_ids,
                prune_orphan_entities=prune_orphan_entities,
            )
            batch_deleted, batch_pruned = self._delete_event_index_batch(
                tenant_id=tenant_id,
                event_ids=event_ids,
                candidate_entity_ids=candidate_entity_ids,
                commit=commit,
                prune_orphan_entities=prune_orphan_entities,
                strict=strict,
            )
            deleted += batch_deleted
            pruned += batch_pruned
            last_event_id = event_ids[-1]

        return {"events_deleted": deleted, "entities_pruned": pruned}

    def rebuild_event_indexes(
        self,
        *,
        tenant_id: UUID,
        document_ids: list[UUID] | None = None,
    ) -> None:
        event_query = self._db.query(KgSourceEvent).filter(KgSourceEvent.tenant_id == tenant_id)
        if document_ids:
            event_query = event_query.filter(KgSourceEvent.document_id.in_(document_ids))
        events = event_query.all()
        if events and settings.EVENT_VECTOR_ENABLED:
            self.write_event_vectors(events)

        event_ids = [ev.id for ev in events]
        if not event_ids:
            return

        entity_id_rows = (
            self._db.query(KgEventEntity.entity_id).filter(KgEventEntity.event_id.in_(event_ids)).distinct().all()
        )
        entity_ids = [row[0] for row in entity_id_rows if row and row[0]]
        if not entity_ids:
            return

        entities = self._db.query(KgEntity).filter(KgEntity.tenant_id == tenant_id, KgEntity.id.in_(entity_ids)).all()
        if entities and settings.ENTITY_VECTOR_ENABLED:
            self.write_entity_vectors(entities)

    def _get_or_create_entity(
        self,
        *,
        tenant_id: UUID,
        name: str,
        normalized_name: str,
        type_: str,
        description: str | None = None,
    ) -> KgEntity:
        existing = (
            self._db.query(KgEntity)
            .filter(
                KgEntity.tenant_id == tenant_id,
                KgEntity.normalized_name == normalized_name,
                KgEntity.type == type_,
            )
            .first()
        )
        if existing:
            return existing

        entity = KgEntity(
            tenant_id=tenant_id,
            name=name,
            normalized_name=normalized_name,
            type=type_,
            description=description,
            vector=None,
            extra_data=None,
        )
        self._db.add(entity)
        self._db.flush()
        return entity

    def write_event_vectors(self, events: Iterable[KgSourceEvent]) -> list[str]:
        items: list[dict[str, Any]] = []
        embeddings: list[list[float]] = []
        for ev in events:
            vector_item = _event_vector_item(ev)
            if vector_item is None:
                continue
            item, vector = vector_item
            items.append(item)
            embeddings.append(vector)

        if not items:
            return []
        try:
            return self._event_vector.add_vectors(items, embeddings=embeddings)
        except Exception as exc:
            logger.warning("Failed to store KG event vectors: %s", exc)
            return []

    def write_entity_vectors(self, entities: Iterable[KgEntity]) -> list[str]:
        items: list[dict[str, Any]] = []
        embeddings: list[list[float]] = []
        for ent in entities:
            if not ent.vector:
                continue
            embeddings.append(list(ent.vector))
            items.append(
                {
                    "id": str(ent.id),
                    "content": ent.name,
                    "metadata": {
                        "name": ent.name,
                        "normalized_name": ent.normalized_name,
                        "tenant_id": str(ent.tenant_id),
                        "type": ent.type,
                        "description": ent.description or "",
                        "index_kind": "entity",
                    },
                }
            )

        if not items:
            return []
        try:
            return self._entity_vector.add_vectors(items, embeddings=embeddings)
        except Exception as exc:
            logger.warning("Failed to store KG entity vectors: %s", exc)
            return []

    def delete_vectors(self, *, event_ids: Sequence[UUID], entity_ids: Sequence[UUID]) -> None:
        if event_ids:
            self._event_vector.delete([str(event_id) for event_id in event_ids])
        if entity_ids:
            self._entity_vector.delete([str(entity_id) for entity_id in entity_ids])
