"""
Entity and Event repositories.

Provides data access for entities and events with both PostgreSQL storage
and Milvus vector similarity search capabilities.
"""
from typing import Iterable, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.database import SessionLocal
from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

class EntityRepository:
    """Entity read/write + similarity search."""

    def __init__(self, session: Session):
        self.session = session
        collection = resolve_collection_name("kg_entities")
        self._milvus = get_milvus_adapter(collection_name=collection, vector_field="embedding")

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

    def get_entities_by_ids(self, ids: Iterable[str]) -> List[KgEntity]:
        id_list = list(ids)
        if not id_list:
            return []
        stmt = select(KgEntity).where(KgEntity.id.in_(id_list))
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
    ) -> KgEntity:
        existing = (
            self.session.execute(
                select(KgEntity).where(
                    KgEntity.tenant_id == tenant_id,
                    KgEntity.normalized_name == normalized_name,
                    KgEntity.type == type_,
                )
            )
            .scalars()
            .first()
        )
        if existing:
            return existing
        ent = KgEntity(
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
        collection = resolve_collection_name("kg_events")
        self._milvus = get_milvus_adapter(collection_name=collection, vector_field="embedding")

    def link_event_entities(
        self,
        links: List[KgEventEntity],
    ) -> None:
        for link in links:
            self.session.merge(link)
        self.session.commit()

    def get_events_by_ids(self, ids: Iterable[str]) -> List[KgSourceEvent]:
        id_list = list(ids)
        if not id_list:
            return []
        stmt = select(KgSourceEvent).where(KgSourceEvent.id.in_(id_list))
        return self.session.execute(stmt).scalars().all()

    def get_events_with_entities(self, ids: Iterable[str]) -> List[KgSourceEvent]:
        id_list = list(ids)
        if not id_list:
            return []
        from sqlalchemy.orm import joinedload

        stmt = (
            select(KgSourceEvent)
            .where(KgSourceEvent.id.in_(id_list))
            .options(
                joinedload(KgSourceEvent.associations).joinedload(KgEventEntity.entity)
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
            select(KgEventEntity.event_id)
            .join(KgSourceEvent, KgSourceEvent.id == KgEventEntity.event_id)
            .where(KgEventEntity.entity_id.in_(ids))
            .where(KgSourceEvent.tenant_id == tenant_id)
        )
        if document_ids:
            stmt = stmt.where(KgSourceEvent.document_id.in_(document_ids))
        rows = self.session.execute(stmt).scalars().all()
        # simple frequency based ranking
        freq: dict[str, int] = {}
        for eid in rows:
            freq[eid] = freq.get(eid, 0) + 1
        ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [eid for eid, _ in ranked[:limit]]

    def get_event_entities(self, event_ids: Iterable[str]) -> dict[str, List[KgEventEntity]]:
        ids = list(event_ids)
        if not ids:
            return {}
        stmt = select(KgEventEntity).where(KgEventEntity.event_id.in_(ids))
        rows = self.session.execute(stmt).scalars().all()
        mapping: dict[str, List[KgEventEntity]] = {}
        for row in rows:
            mapping.setdefault(str(row.event_id), []).append(row)
        return mapping

    def get_entities_for_events(self, event_ids: Iterable[str]) -> dict[str, List[KgEntity]]:
        ids = list(event_ids)
        if not ids:
            return {}
        stmt = (
            select(KgEventEntity, KgEntity)
            .join(KgEntity, KgEntity.id == KgEventEntity.entity_id)
            .where(KgEventEntity.event_id.in_(ids))
        )
        rows = self.session.execute(stmt).all()
        mapping: dict[str, List[KgEntity]] = {}
        for assoc, ent in rows:
            mapping.setdefault(str(assoc.event_id), []).append(ent)
        return mapping

    def find_events_by_entities(
        self,
        entity_ids: Iterable[str],
        tenant_id,
        limit: int = 50,
        document_ids: Optional[List[UUID]] = None,
    ) -> List[KgSourceEvent]:
        ids = list(entity_ids)
        if not ids:
            return []
        stmt = (
            select(KgSourceEvent)
            .join(KgEventEntity, KgEventEntity.event_id == KgSourceEvent.id)
            .where(KgEventEntity.entity_id.in_(ids))
            .where(KgSourceEvent.tenant_id == tenant_id)
            .limit(limit)
        )
        if document_ids:
            stmt = stmt.where(KgSourceEvent.document_id.in_(document_ids))
        return self.session.execute(stmt).scalars().all()


def get_session() -> Session:
    return SessionLocal()
