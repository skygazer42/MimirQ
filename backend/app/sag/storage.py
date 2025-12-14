"""
Lightweight repositories for SAG using PostgreSQL JSON vectors.
"""
import math
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.core.database import SessionLocal
from app.models.sag_entities import SagEntity, SagSourceEvent, SagEventEntity


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

    def upsert_entities(self, entities: List[SagEntity]) -> List[SagEntity]:
        for ent in entities:
            self.session.merge(ent)
        self.session.commit()
        return entities

    def search_similar(
        self,
        query_vector: List[float],
        tenant_id,
        k: int = 10,
        entity_type: Optional[str] = None,
    ) -> List[dict]:
        stmt = select(SagEntity).where(SagEntity.tenant_id == tenant_id)
        if entity_type:
            stmt = stmt.where(SagEntity.type == entity_type)
        rows = self.session.execute(stmt).scalars().all()
        results = []
        for row in rows:
            if not row.vector:
                continue
            sim = _cosine(query_vector, row.vector)
            results.append(
                {
                    "entity_id": str(row.id),
                    "name": row.name,
                    "type": row.type,
                    "similarity": float(sim),
                    "tenant_id": str(row.tenant_id),
                }
            )
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:k]

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
        self.session.commit()
        self.session.refresh(ent)
        return ent


class EventRepository:
    """Event read/write + similarity search."""

    def __init__(self, session: Session):
        self.session = session

    def upsert_events(self, events: List[SagSourceEvent]) -> List[SagSourceEvent]:
        for ev in events:
            self.session.merge(ev)
        self.session.commit()
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
    ) -> List[dict]:
        stmt = select(SagSourceEvent).where(SagSourceEvent.tenant_id == tenant_id)
        rows = self.session.execute(stmt).scalars().all()
        results = []
        for row in rows:
            if not row.content_vector:
                continue
            sim = _cosine(query_vector, row.content_vector)
            results.append(
                {
                    "event_id": str(row.id),
                    "title": row.title,
                    "summary": row.summary,
                    "similarity": float(sim),
                    "tenant_id": str(row.tenant_id),
                    "chunk_id": str(row.chunk_id) if row.chunk_id else None,
                    "document_id": str(row.document_id) if row.document_id else None,
                }
            )
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:k]

    def search_events_by_entities(
        self,
        entity_ids: Iterable[str],
        tenant_id,
        limit: int = 50,
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
        self, entity_ids: Iterable[str], tenant_id, limit: int = 50
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
        return self.session.execute(stmt).scalars().all()


def get_session() -> Session:
    return SessionLocal()
