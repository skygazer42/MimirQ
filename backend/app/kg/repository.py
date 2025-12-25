"""
Entity and Event repositories.

Provides data access for entities and events with both PostgreSQL storage
and Milvus vector similarity search capabilities.
"""
import math
from typing import Any, Iterable, List, Optional, Dict
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.core.database import SessionLocal
from app.kg.models import SagEntity, SagSourceEvent, SagEventEntity
from app.core.config import settings
from app.storage.vector.milvus import MilvusAdapter


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EntityRepository:
    """Entity read/write + similarity search."""

    def __init__(self, session: Session):
        self.session = session
        self._milvus = MilvusAdapter(collection_name="sag_entities", vector_field="embedding")

    def push_entities_to_milvus(self, entities: List[SagEntity]) -> List[str]:
        items: List[Dict[str, Any]] = []
        embeddings: List[List[float]] = []
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
                        "tenant_id": str(ent.tenant_id),
                        "type": ent.type,
                        "description": ent.description or "",
                    },
                }
            )
        if not items:
            return []
        return self._milvus.add_vectors(items, embeddings=embeddings)

    def upsert_entities(self, entities: List[SagEntity]) -> List[SagEntity]:
        for ent in entities:
            self.session.merge(ent)
        self.session.commit()

        self.push_entities_to_milvus(entities)
        return entities

    def search_similar(
        self,
        query_vector: List[float],
        tenant_id,
        k: int = 10,
        entity_type: Optional[str] = None,
    ) -> List[dict]:
        expr_parts = [f'tenant_id == "{str(tenant_id)}"']
        if entity_type:
            expr_parts.append(f'type == "{entity_type}"')
        expr = " and ".join(expr_parts)

        results = self._milvus.search(query_vector=query_vector, top_k=k, expr=expr)
        formatted = []
        for r in results:
            meta = r.get("metadata") or {}
            formatted.append(
                {
                    "entity_id": meta.get("id") or r.get("id"),
                    "name": meta.get("name") or meta.get("content") or "",
                    "type": meta.get("type") or "unknown",
                    "similarity": r.get("score", 0.0),
                    "tenant_id": meta.get("tenant_id"),
                }
            )
        return formatted

    def get_entities_by_ids(self, ids: Iterable[str]) -> List[SagEntity]:
        id_list = list(ids)
        if not id_list:
            return []
        stmt = select(SagEntity).where(SagEntity.id.in_(id_list))
        return self.session.execute(stmt).scalars().all()

    def get_or_create(
        self,
        tenant_id,
        name: str,
        normalized_name: str,
        type_: str,
        description: Optional[str] = None,
        *,
        commit: bool = True,
    ) -> SagEntity:
        existing = (
            self.session.execute(
                select(SagEntity).where(
                    SagEntity.tenant_id == tenant_id,
                    SagEntity.normalized_name == normalized_name,
                    SagEntity.type == type_,
                )
            )
            .scalars()
            .first()
        )
        if existing:
            return existing
        ent = SagEntity(
            tenant_id=tenant_id,
            name=name,
            normalized_name=normalized_name,
            type=type_,
            description=description,
            vector=None,
            extra_data=None,
        )
        self.session.add(ent)
        if commit:
            self.session.commit()
            self.session.refresh(ent)
        else:
            self.session.flush()
        return ent


class EventRepository:
    """Event read/write + similarity search."""

    def __init__(self, session: Session):
        self.session = session
        self._milvus = MilvusAdapter(collection_name="sag_events", vector_field="embedding")

    def push_events_to_milvus(self, events: List[SagSourceEvent]) -> List[str]:
        items: List[Dict[str, Any]] = []
        embeddings: List[List[float]] = []
        for ev in events:
            if not ev.content_vector:
                continue
            embeddings.append(list(ev.content_vector))
            items.append(
                {
                    "id": str(ev.id),
                    "content": ev.content,
                    "metadata": {
                        "tenant_id": str(ev.tenant_id),
                        "document_id": str(ev.document_id) if ev.document_id else "",
                        "chunk_id": str(ev.chunk_id) if ev.chunk_id else "",
                        "title": ev.title,
                        "summary": ev.summary,
                    },
                }
            )
        if not items:
            return []
        return self._milvus.add_vectors(items, embeddings=embeddings)

    def upsert_events(self, events: List[SagSourceEvent]) -> List[SagSourceEvent]:
        for ev in events:
            self.session.merge(ev)
        self.session.commit()

        self.push_events_to_milvus(events)
        return events

    def link_event_entities(
        self,
        links: List[SagEventEntity],
    ) -> None:
        for link in links:
            self.session.merge(link)
        self.session.commit()

    def get_events_by_ids(self, ids: Iterable[str]) -> List[SagSourceEvent]:
        id_list = list(ids)
        if not id_list:
            return []
        stmt = select(SagSourceEvent).where(SagSourceEvent.id.in_(id_list))
        return self.session.execute(stmt).scalars().all()

    def get_events_with_entities(self, ids: Iterable[str]) -> List[SagSourceEvent]:
        id_list = list(ids)
        if not id_list:
            return []
        from sqlalchemy.orm import joinedload

        stmt = (
            select(SagSourceEvent)
            .where(SagSourceEvent.id.in_(id_list))
            .options(
                joinedload(SagSourceEvent.associations).joinedload(SagEventEntity.entity)
            )
        )
        return self.session.execute(stmt).scalars().all()

    def search_similar_by_content(
        self,
        query_vector: List[float],
        tenant_id,
        k: int = 20,
        document_ids: Optional[List[UUID]] = None,
    ) -> List[dict]:
        expr_parts = [f'tenant_id == "{str(tenant_id)}"']
        if document_ids:
            doc_id_strs = [f'"{str(doc_id)}"' for doc_id in document_ids]
            expr_parts.append(f"document_id in [{', '.join(doc_id_strs)}]")
        expr = " and ".join(expr_parts)
        results = self._milvus.search(query_vector=query_vector, top_k=k, expr=expr)
        formatted = []
        for r in results:
            meta = r.get("metadata") or {}
            formatted.append(
                {
                    "event_id": meta.get("id") or r.get("id"),
                    "title": meta.get("title") or "",
                    "summary": meta.get("summary") or "",
                    "similarity": r.get("score", 0.0),
                    "tenant_id": meta.get("tenant_id"),
                    "chunk_id": meta.get("chunk_id"),
                    "document_id": meta.get("document_id"),
                }
            )
        return formatted

    def search_events_by_entities(
        self,
        entity_ids: Iterable[str],
        tenant_id,
        limit: int = 50,
        document_ids: Optional[List[UUID]] = None,
    ) -> List[str]:
        ids = list(entity_ids)
        if not ids:
            return []
        stmt = (
            select(SagEventEntity.event_id)
            .join(SagSourceEvent, SagSourceEvent.id == SagEventEntity.event_id)
            .where(SagEventEntity.entity_id.in_(ids))
            .where(SagSourceEvent.tenant_id == tenant_id)
        )
        if document_ids:
            stmt = stmt.where(SagSourceEvent.document_id.in_(document_ids))
        rows = self.session.execute(stmt).scalars().all()
        # simple frequency based ranking
        freq: dict[str, int] = {}
        for eid in rows:
            freq[eid] = freq.get(eid, 0) + 1
        ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [eid for eid, _ in ranked[:limit]]

    def get_event_entities(self, event_ids: Iterable[str]) -> dict[str, List[SagEventEntity]]:
        ids = list(event_ids)
        if not ids:
            return {}
        stmt = select(SagEventEntity).where(SagEventEntity.event_id.in_(ids))
        rows = self.session.execute(stmt).scalars().all()
        mapping: dict[str, List[SagEventEntity]] = {}
        for row in rows:
            mapping.setdefault(str(row.event_id), []).append(row)
        return mapping

    def get_entities_for_events(self, event_ids: Iterable[str]) -> dict[str, List[SagEntity]]:
        ids = list(event_ids)
        if not ids:
            return {}
        stmt = (
            select(SagEventEntity, SagEntity)
            .join(SagEntity, SagEntity.id == SagEventEntity.entity_id)
            .where(SagEventEntity.event_id.in_(ids))
        )
        rows = self.session.execute(stmt).all()
        mapping: dict[str, List[SagEntity]] = {}
        for assoc, ent in rows:
            mapping.setdefault(str(assoc.event_id), []).append(ent)
        return mapping

    def find_events_by_entities(
        self,
        entity_ids: Iterable[str],
        tenant_id,
        limit: int = 50,
        document_ids: Optional[List[UUID]] = None,
    ) -> List[SagSourceEvent]:
        ids = list(entity_ids)
        if not ids:
            return []
        stmt = (
            select(SagSourceEvent)
            .join(SagEventEntity, SagEventEntity.event_id == SagSourceEvent.id)
            .where(SagEventEntity.entity_id.in_(ids))
            .where(SagSourceEvent.tenant_id == tenant_id)
            .limit(limit)
        )
        if document_ids:
            stmt = stmt.where(SagSourceEvent.document_id.in_(document_ids))
        return self.session.execute(stmt).scalars().all()


def get_session() -> Session:
    return SessionLocal()
