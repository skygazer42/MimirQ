from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from langchain_core.documents import Document as LCDocument
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.kg.models import SagEntity, SagEventEntity, SagSourceEvent
from app.models.document import Document as DBDocument, DocumentChunk
from app.rag.retrieval.hybrid_retriever import hybrid_retriever
from app.storage.vector.factory import get_vector_store
from app.storage.vector.milvus import get_milvus_adapter

logger = logging.getLogger("indexer")


class IndexKind(str, Enum):
    CHUNK = "chunk"
    EVENT = "event"


@dataclass(frozen=True)
class IndexScope:
    tenant_id: UUID
    document_id: Optional[UUID] = None
    document_ids: Optional[List[UUID]] = None


@dataclass(frozen=True)
class IndexingOptions:
    chunk_vector_enabled: Optional[bool] = None
    bm25_index_enabled: Optional[bool] = None
    event_vector_enabled: Optional[bool] = None
    entity_vector_enabled: Optional[bool] = None


@dataclass(frozen=True)
class ChunkInput:
    content: str
    metadata: Dict[str, Any]
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None


@dataclass(frozen=True)
class PersistChunksResult:
    db_chunks: List[DocumentChunk]
    chunk_ids: List[UUID]
    vector_ids: List[Optional[str]]
    total_characters: int


@dataclass(frozen=True)
class EventEntityInput:
    name: str
    normalized_name: str
    type: str
    description: Optional[str] = None
    vector: Optional[List[float]] = None
    role: Optional[str] = None


@dataclass(frozen=True)
class EventInput:
    title: str
    summary: str
    content: str
    document_id: Optional[UUID]
    chunk_id: Optional[UUID]
    references: Optional[Dict[str, Any]] = None
    vector: Optional[List[float]] = None
    entities: List[EventEntityInput] = field(default_factory=list)


@dataclass(frozen=True)
class IndexRecord:
    kind: IndexKind
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    document_id: Optional[UUID] = None
    chunk_id: Optional[UUID] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    references: Optional[Dict[str, Any]] = None
    vector: Optional[List[float]] = None
    entities: List[EventEntityInput] = field(default_factory=list)
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None


@dataclass(frozen=True)
class PersistEventsResult:
    events: List[SagSourceEvent]
    entities: List[SagEntity]
    event_ids: List[UUID]
    entity_ids: List[UUID]
    event_vector_ids: List[str]
    entity_vector_ids: List[str]


@dataclass(frozen=True)
class IndexBatchResult:
    chunk_result: Optional[PersistChunksResult] = None
    event_result: Optional[PersistEventsResult] = None


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


class Indexer:
    """
    Unified Indexer for chunk/event indexing.

    - Chunk indexing: vector store + PostgreSQL + BM25
    - Event indexing: PostgreSQL + Milvus (events + entities)
    """

    def __init__(self, db: Session):
        self._db = db
        self._event_vector = get_milvus_adapter(collection_name="sag_events", vector_field="embedding")
        self._entity_vector = get_milvus_adapter(collection_name="sag_entities", vector_field="embedding")

    def _resolve_chunk_vector_enabled(self, options: Optional[IndexingOptions]) -> bool:
        if options and options.chunk_vector_enabled is not None:
            return bool(options.chunk_vector_enabled)
        return bool(getattr(settings, "CHUNK_VECTOR_ENABLED", True))

    def _resolve_bm25_enabled(self, options: Optional[IndexingOptions]) -> bool:
        if options and options.bm25_index_enabled is not None:
            return bool(options.bm25_index_enabled)
        return bool(getattr(settings, "BM25_INDEX_ENABLED", True))

    def _resolve_event_vector_enabled(self, options: Optional[IndexingOptions]) -> bool:
        if options and options.event_vector_enabled is not None:
            return bool(options.event_vector_enabled)
        return bool(getattr(settings, "EVENT_VECTOR_ENABLED", True))

    def _resolve_entity_vector_enabled(self, options: Optional[IndexingOptions]) -> bool:
        if options and options.entity_vector_enabled is not None:
            return bool(options.entity_vector_enabled)
        return bool(getattr(settings, "ENTITY_VECTOR_ENABLED", True))

    def index(self, kind: IndexKind, **kwargs):
        if kind == IndexKind.CHUNK:
            return self.index_chunks(**kwargs)
        if kind == IndexKind.EVENT:
            return self.index_events(**kwargs)
        raise ValueError(f"Unsupported index kind: {kind}")

    def upsert(
        self,
        *,
        tenant_id: UUID,
        records: Sequence[IndexRecord],
        default_source: str = "unknown",
        commit: bool = True,
        options: Optional[IndexingOptions] = None,
    ) -> IndexBatchResult:
        start = time.time()
        if not records:
            return IndexBatchResult()

        chunk_records = [r for r in records if r.kind == IndexKind.CHUNK]
        event_records = [r for r in records if r.kind == IndexKind.EVENT]
        unknown_kinds = {r.kind for r in records if r.kind not in (IndexKind.CHUNK, IndexKind.EVENT)}
        if unknown_kinds:
            raise ValueError(f"Unsupported index kinds: {sorted(unknown_kinds)}")

        chunk_result: Optional[PersistChunksResult] = None
        if chunk_records:
            doc_ids = {r.document_id for r in chunk_records if r.document_id is not None}
            if not doc_ids:
                raise ValueError("Chunk records require document_id")
            if len(doc_ids) != 1:
                raise ValueError("Chunk records must share a single document_id per upsert call")
            document_id = next(iter(doc_ids))
            chunk_inputs = [self._record_to_chunk_input(r) for r in chunk_records]
            chunk_result = self.index_chunks(
                document_id=document_id,
                tenant_id=tenant_id,
                chunks=chunk_inputs,
                default_source=default_source,
                commit=commit,
                options=options,
            )

        event_result: Optional[PersistEventsResult] = None
        if event_records:
            event_inputs = [self._record_to_event_input(r) for r in event_records]
            event_result = self.index_events(
                tenant_id=tenant_id,
                events=event_inputs,
                commit=commit,
                options=options,
            )

        elapsed = time.time() - start
        logger.info(
            "indexer.upsert tenant=%s chunks=%s events=%s elapsed=%.3fs",
            tenant_id,
            len(chunk_records),
            len(event_records),
            elapsed,
        )
        return IndexBatchResult(chunk_result=chunk_result, event_result=event_result)

    def delete(self, kind: IndexKind, **kwargs) -> None:
        if kind == IndexKind.CHUNK:
            return self.delete_chunk_indexes(**kwargs)
        if kind == IndexKind.EVENT:
            return self.delete_event_indexes(**kwargs)
        raise ValueError(f"Unsupported index kind: {kind}")

    def delete_all(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        commit: bool = True,
    ) -> None:
        self.delete(IndexKind.CHUNK, tenant_id=tenant_id, document_id=document_id)
        self.delete(IndexKind.EVENT, tenant_id=tenant_id, document_id=document_id, commit=commit)

    def rebuild(self, kind: IndexKind, **kwargs) -> None:
        if kind == IndexKind.CHUNK:
            return self.rebuild_chunk_indexes(**kwargs)
        if kind == IndexKind.EVENT:
            return self.rebuild_event_indexes(**kwargs)
        raise ValueError(f"Unsupported index kind: {kind}")

    def rebuild_all(
        self,
        *,
        tenant_id: UUID,
        document_ids: Optional[List[UUID]] = None,
    ) -> None:
        self.rebuild_tenant(tenant_id=tenant_id, document_ids=document_ids)

    def rebuild_tenant(
        self,
        *,
        tenant_id: UUID,
        document_ids: Optional[List[UUID]] = None,
        kinds: Optional[Sequence[IndexKind]] = None,
    ) -> None:
        active = set(kinds or (IndexKind.CHUNK, IndexKind.EVENT))
        if IndexKind.CHUNK in active:
            self.rebuild_chunk_indexes(tenant_id=tenant_id, document_ids=document_ids)
        if IndexKind.EVENT in active:
            self.rebuild_event_indexes(tenant_id=tenant_id, document_ids=document_ids)

    def index_chunks(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        chunks: List[ChunkInput],
        default_source: str = "unknown",
        commit: bool = True,
        options: Optional[IndexingOptions] = None,
    ) -> PersistChunksResult:
        total_characters = sum(len(c.content or "") for c in chunks)
        normalized_chunks: List[ChunkInput] = []
        vector_docs: List[Dict[str, Any]] = []
        for c in chunks:
            meta = dict(c.metadata or {})
            meta.setdefault("index_kind", IndexKind.CHUNK.value)
            normalized_chunks.append(
                ChunkInput(
                    content=c.content,
                    metadata=meta,
                    page_number=c.page_number,
                    start_char=c.start_char,
                    end_char=c.end_char,
                )
            )
            vector_docs.append({"content": c.content, "metadata": meta})

        vector_ids = self._index_chunk_vectors(
            vector_docs,
            document_id=document_id,
            tenant_id=tenant_id,
            enable_vectors=self._resolve_chunk_vector_enabled(options),
        )
        db_chunks = self._persist_document_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
            chunks=normalized_chunks,
            vector_ids=vector_ids,
            commit=commit,
        )

        try:
            self._update_bm25_for_chunks(
                db_chunks=db_chunks,
                tenant_id=tenant_id,
                document_id=document_id,
                default_source=default_source,
                enable_bm25=self._resolve_bm25_enabled(options),
            )
        except Exception as exc:
            print(f"[WARN]  Failed to update BM25 index incrementally: {exc}")

        return PersistChunksResult(
            db_chunks=db_chunks,
            chunk_ids=[c.id for c in db_chunks],
            vector_ids=vector_ids,
            total_characters=total_characters,
        )

    def index_events(
        self,
        *,
        tenant_id: UUID,
        events: Sequence[EventInput],
        commit: bool = True,
        options: Optional[IndexingOptions] = None,
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

        entity_cache: Dict[Tuple[str, str, str], SagEntity] = {}
        db_events: List[SagSourceEvent] = []

        for item in events:
            event_obj = SagSourceEvent(
                tenant_id=tenant_id,
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                title=item.title,
                summary=item.summary,
                content=item.content,
                content_vector=item.vector,
                references=item.references,
            )
            self._db.add(event_obj)
            db_events.append(event_obj)

            for ent in item.entities:
                name = ent.name.strip()
                if not name:
                    continue
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

                if ent.vector and not getattr(entity_obj, "vector", None):
                    entity_obj.vector = ent.vector

                self._db.add(
                    SagEventEntity(
                        event=event_obj,
                        entity=entity_obj,
                        weight=1.0,
                        role=ent.role,
                    )
                )

        if commit:
            self._db.commit()
        else:
            self._db.flush()

        event_vector_ids: List[str] = []
        entity_vector_ids: List[str] = []
        if commit:
            if self._resolve_event_vector_enabled(options):
                event_vector_ids = self._index_event_vectors(db_events)
            if self._resolve_entity_vector_enabled(options):
                entity_vector_ids = self._index_entity_vectors(list(entity_cache.values()))

        return PersistEventsResult(
            events=db_events,
            entities=list(entity_cache.values()),
            event_ids=[ev.id for ev in db_events],
            entity_ids=[ent.id for ent in entity_cache.values()],
            event_vector_ids=event_vector_ids,
            entity_vector_ids=entity_vector_ids,
        )

    def delete_chunk_indexes(self, *, tenant_id: UUID, document_id: UUID) -> None:
        try:
            get_vector_store().delete_by_document_id(document_id, tenant_id=tenant_id)
        except Exception as exc:
            print(f"[WARN]  Failed to delete vectors: {exc}")

        try:
            hybrid_retriever.remove_document_from_bm25_index(document_id, tenant_id=tenant_id)
        except Exception as exc:
            print(f"[WARN]  Failed to update BM25 index after deletion: {exc}")

    def delete_event_indexes(self, *, tenant_id: UUID, document_id: UUID, commit: bool = True) -> None:
        query = self._db.query(SagSourceEvent).filter(
            SagSourceEvent.tenant_id == tenant_id,
            SagSourceEvent.document_id == document_id,
        )
        events = query.all()
        if events:
            event_ids = [str(ev.id) for ev in events]
            try:
                self._event_vector.delete(event_ids)
            except Exception as exc:
                print(f"[WARN]  Failed to delete SAG event vectors: {exc}")

            query.delete(synchronize_session=False)
            if commit:
                self._db.commit()
            else:
                self._db.flush()

    def rebuild_chunk_indexes(
        self,
        *,
        tenant_id: UUID,
        document_ids: Optional[List[UUID]] = None,
    ) -> None:
        if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
            return

        query = (
            self._db.query(DocumentChunk)
            .join(DBDocument)
            .filter(DBDocument.status == "completed")
            .filter(DocumentChunk.tenant_id == tenant_id)
        )
        if document_ids:
            query = query.filter(DocumentChunk.document_id.in_(document_ids))

        chunks = query.all()
        if not chunks:
            print("[WARN]  No chunks found for BM25 index")
            return

        hybrid_retriever.build_bm25_index(chunks, tenant_id=tenant_id)

    def rebuild_event_indexes(
        self,
        *,
        tenant_id: UUID,
        document_ids: Optional[List[UUID]] = None,
    ) -> None:
        event_query = self._db.query(SagSourceEvent).filter(SagSourceEvent.tenant_id == tenant_id)
        if document_ids:
            event_query = event_query.filter(SagSourceEvent.document_id.in_(document_ids))
        events = event_query.all()
        if events and bool(getattr(settings, "EVENT_VECTOR_ENABLED", True)):
            self._index_event_vectors(events)

        event_ids = [ev.id for ev in events]
        if not event_ids:
            return

        entity_id_rows = (
            self._db.query(SagEventEntity.entity_id)
            .filter(SagEventEntity.event_id.in_(event_ids))
            .distinct()
            .all()
        )
        entity_ids = [row[0] for row in entity_id_rows if row and row[0]]
        if not entity_ids:
            return

        entities = (
            self._db.query(SagEntity)
            .filter(SagEntity.tenant_id == tenant_id, SagEntity.id.in_(entity_ids))
            .all()
        )
        if entities and bool(getattr(settings, "ENTITY_VECTOR_ENABLED", True)):
            self._index_entity_vectors(entities)

    def _record_to_chunk_input(self, record: IndexRecord) -> ChunkInput:
        meta = dict(record.metadata or {})
        page_number = record.page_number if record.page_number is not None else meta.get("page") or meta.get("page_number")
        start_char = record.start_char if record.start_char is not None else meta.get("start_char")
        end_char = record.end_char if record.end_char is not None else meta.get("end_char")
        return ChunkInput(
            content=record.content,
            metadata=meta,
            page_number=page_number,
            start_char=start_char,
            end_char=end_char,
        )

    def _record_to_event_input(self, record: IndexRecord) -> EventInput:
        title = (record.title or "").strip()
        summary = (record.summary or "").strip()
        content = (record.content or "").strip()
        if not content:
            content = summary or title
        if not title:
            title = (summary[:50] if summary else content[:50]).strip() or "Event"
        if not summary:
            summary = (content[:200] if content else title).strip() or "Event"
        return EventInput(
            title=title,
            summary=summary,
            content=content,
            document_id=record.document_id,
            chunk_id=record.chunk_id,
            references=record.references,
            vector=record.vector,
            entities=list(record.entities or []),
        )

    def _index_chunk_vectors(
        self,
        docs: List[dict],
        *,
        document_id: UUID,
        tenant_id: UUID,
        enable_vectors: bool,
    ) -> List[Optional[str]]:
        if not docs:
            return []

        if not enable_vectors:
            return [None] * len(docs)

        vector_store = get_vector_store()
        try:
            return list(vector_store.add_documents(docs, document_id, tenant_id))
        except Exception as exc:
            print(f"[WARN]  Failed to store vectors: {exc}")
            print("[WARN]  Proceeding without vector ids; BM25-only retrieval will still work.")
            return [None] * len(docs)

    def _persist_document_chunks(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        chunks: List[ChunkInput],
        vector_ids: Optional[List[Optional[str]]] = None,
        commit: bool = True,
    ) -> List[DocumentChunk]:
        if not chunks:
            return []

        if vector_ids is None:
            vector_ids = [None] * len(chunks)
        if len(vector_ids) != len(chunks):
            raise ValueError(f"vector_ids length {len(vector_ids)} != chunks length {len(chunks)}")

        db_chunks: List[DocumentChunk] = []
        for idx, (chunk, vector_id) in enumerate(zip(chunks, vector_ids)):
            meta = dict(chunk.metadata or {})
            page_number = (
                _safe_int(chunk.page_number)
                if chunk.page_number is not None
                else _safe_int(meta.get("page") or meta.get("page_number"))
            )
            start_char = _safe_int(chunk.start_char) if chunk.start_char is not None else _safe_int(meta.get("start_char"))
            end_char = _safe_int(chunk.end_char) if chunk.end_char is not None else _safe_int(meta.get("end_char"))

            db_chunks.append(
                DocumentChunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_index=idx,
                    content=chunk.content,
                    page_number=page_number,
                    start_char=start_char,
                    end_char=end_char,
                    doc_metadata=meta,
                    vector_id=vector_id,
                )
            )

        self._db.add_all(db_chunks)
        self._db.flush()
        if commit:
            self._db.commit()

        return db_chunks

    def _update_bm25_for_chunks(
        self,
        *,
        db_chunks: List[DocumentChunk],
        tenant_id: UUID,
        document_id: UUID,
        default_source: str = "unknown",
        enable_bm25: bool,
    ) -> None:
        if not db_chunks:
            return
        if not enable_bm25:
            return

        bm25_docs: List[LCDocument] = []
        for db_chunk in db_chunks:
            meta = dict(db_chunk.doc_metadata or {})
            meta.setdefault("index_kind", IndexKind.CHUNK.value)
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("chunk_index", db_chunk.chunk_index)
            meta.setdefault("source", meta.get("source", default_source))
            meta.setdefault("page", db_chunk.page_number)
            meta.setdefault("image_id", meta.get("image_id"))
            meta.setdefault("image_url", meta.get("image_url"))
            bm25_docs.append(LCDocument(page_content=db_chunk.content, id=str(db_chunk.id), metadata=meta))

        hybrid_retriever.upsert_bm25_documents(bm25_docs, tenant_id=tenant_id)

    def _get_or_create_entity(
        self,
        *,
        tenant_id: UUID,
        name: str,
        normalized_name: str,
        type_: str,
        description: Optional[str] = None,
    ) -> SagEntity:
        existing = (
            self._db.query(SagEntity)
            .filter(
                SagEntity.tenant_id == tenant_id,
                SagEntity.normalized_name == normalized_name,
                SagEntity.type == type_,
            )
            .first()
        )
        if existing:
            return existing

        entity = SagEntity(
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

    def _index_event_vectors(self, events: Iterable[SagSourceEvent]) -> List[str]:
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
                        "index_kind": IndexKind.EVENT.value,
                    },
                }
            )

        if not items:
            return []
        try:
            return self._event_vector.add_vectors(items, embeddings=embeddings)
        except Exception as exc:
            print(f"[WARN]  Failed to store SAG event vectors: {exc}")
            return []

    def _index_entity_vectors(self, entities: Iterable[SagEntity]) -> List[str]:
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
                        "index_kind": "entity",
                    },
                }
            )

        if not items:
            return []
        try:
            return self._entity_vector.add_vectors(items, embeddings=embeddings)
        except Exception as exc:
            print(f"[WARN]  Failed to store SAG entity vectors: {exc}")
            return []
