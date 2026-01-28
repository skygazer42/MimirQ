"""
Indexing service implementation.

Provides a unified interface for document chunk and event indexing.
"""
import asyncio
import hashlib
import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import uuid
from uuid import UUID

from langchain_core.documents import Document as LCDocument
from sqlalchemy.orm import Session

from app.types.indexing import (
    ChunkInput,
    EventInput,
    IndexBatchResult,
    IndexKind,
    IndexingOptions,
    IndexRecord,
    PersistChunksResult,
    PersistEventsResult,
)
from app.core.config import settings
from app.rag.kg.models import KgEntity, KgEventEntity, KgSourceEvent
from app.models.document import DocumentChunk
from app.rag.retriever import hybrid_retriever
from app.storage.vector.factory import get_vector_store
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name
from app.rag.core.metadata import normalize_image_metadata
from app.rag.preprocessing.normalization import normalize_text
from app.services.metrics_logger import log_metrics

logger = logging.getLogger("indexer")


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _ensure_chunk_metadata(
    meta: Dict[str, Any],
    *,
    content: str,
    document_id: UUID,
    chunk_index: int,
) -> Dict[str, Any]:
    """Ensure stable per-chunk metadata fields exist (used across DB/vector/BM25)."""
    if not isinstance(meta, dict):
        meta = {}

    meta.setdefault("chunk_key", f"{str(document_id)}:{int(chunk_index)}")

    normalized = normalize_text(content or "", normalize_line_endings=True, remove_control_chars=True)
    stripped = (normalized or "").strip()
    meta.setdefault("content_len", int(len(stripped)))

    raw_hash = meta.get("content_hash")
    if not isinstance(raw_hash, str) or not raw_hash.strip():
        meta["content_hash"] = hashlib.sha256(stripped.encode("utf-8", "ignore")).hexdigest()
        meta.setdefault("content_hash_algo", "sha256")

    return meta


def _should_prefix_embedding(meta: Dict[str, Any]) -> bool:
    """Best-effort filter: avoid prefixing non-text assets (images/tables)."""
    doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
    if doc_type in {"image", "table"}:
        return False
    if meta.get("image") is not None:
        return False
    if meta.get("img_id") or meta.get("image_id") or meta.get("image_url"):
        return False
    return True


def _build_embedding_text(content: str, meta: Dict[str, Any], *, max_prefix_chars: int = 180) -> str:
    """
    Build the text used for embedding (vector similarity).

    Rationale: add lightweight structural context (e.g. header_path/outline path) to reduce
    "contextless fragments" without changing stored chunk content (DB) or offsets.
    """
    if not content:
        return content
    if not _should_prefix_embedding(meta):
        return content

    header = meta.get("header_path") or meta.get("outline_path_str") or meta.get("header_context") or None
    if header is None:
        # Some chunkers store outline/header as list.
        header_list = meta.get("outline_path") or meta.get("header_path_list") or None
        if isinstance(header_list, list) and header_list:
            header = " / ".join([str(x).strip() for x in header_list if str(x).strip()][:10])

    header_str = str(header or "").strip()
    if not header_str:
        return content

    header_str = header_str[: max(20, int(max_prefix_chars or 0))]
    prefix = f"[Section] {header_str}\n"
    return prefix + content


class Indexer:
    """
    Unified Indexer for chunk/event indexing.

    - Chunk indexing: vector store + PostgreSQL + BM25
    - Event indexing: PostgreSQL + Milvus (events + entities)
    """

    def __init__(self, db: Session):
        self._db = db
        event_collection = resolve_collection_name("kg_events")
        entity_collection = resolve_collection_name("kg_entities")
        self._event_vector = get_milvus_adapter(collection_name=event_collection, vector_field="embedding")
        self._entity_vector = get_milvus_adapter(collection_name=entity_collection, vector_field="embedding")

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
        source = str(default_source or "").strip() or "unknown"
        total_characters = sum(len(c.content or "") for c in chunks)
        normalized_chunks: List[ChunkInput] = []
        vector_docs: List[Dict[str, Any]] = []
        chunk_ids: List[UUID] = []
        embedding_prefix_enabled = bool(getattr(options, "embedding_context_prefix_enabled", False)) if options else False
        for idx, c in enumerate(chunks):
            meta = dict(c.metadata or {})
            meta.setdefault("index_kind", IndexKind.CHUNK.value)
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("source", source)
            if embedding_prefix_enabled:
                meta.setdefault("embedding_context_prefix_enabled", True)
            meta = _ensure_chunk_metadata(meta, content=c.content or "", document_id=document_id, chunk_index=idx)
            # Ensure every chunk has a stable UUID for cross-system linking.
            chunk_id = _safe_uuid(meta.get("chunk_id")) or uuid.uuid4()
            meta["chunk_id"] = str(chunk_id)
            chunk_ids.append(chunk_id)
            normalized_chunks.append(
                ChunkInput(
                    content=c.content,
                    metadata=meta,
                    page_number=c.page_number,
                    start_char=c.start_char,
                    end_char=c.end_char,
                )
            )
            embed_text = _build_embedding_text(c.content or "", meta) if embedding_prefix_enabled else (c.content or "")
            vector_docs.append({"content": embed_text, "metadata": meta})

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
            chunk_ids=chunk_ids,
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
            logger.warning("Failed to update BM25 index incrementally: %s", exc)

        return PersistChunksResult(
            db_chunks=db_chunks,
            chunk_ids=[c.id for c in db_chunks],
            vector_ids=vector_ids,
            total_characters=total_characters,
        )

    async def index_chunks_async(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        chunks: List[ChunkInput],
        default_source: str = "unknown",
        commit: bool = True,
        options: Optional[IndexingOptions] = None,
    ) -> PersistChunksResult:
        """
        Concurrently index document chunks (vector store, PostgreSQL, BM25).

        Args:
            document_id: Document ID.
            tenant_id: Tenant ID.
            chunks: Chunk list.
            default_source: Default source.
            commit: Whether to commit DB transaction.
            options: Indexing options.

        Returns:
            Persistence result.
        """
        source = str(default_source or "").strip() or "unknown"
        total_characters = sum(len(c.content or "") for c in chunks)
        normalized_chunks: List[ChunkInput] = []
        vector_docs: List[Dict[str, Any]] = []
        chunk_ids: List[UUID] = []
        embedding_prefix_enabled = bool(getattr(options, "embedding_context_prefix_enabled", False)) if options else False
        
        for c in chunks:
            meta = dict(c.metadata or {})
            meta.setdefault("index_kind", IndexKind.CHUNK.value)
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("source", source)
            if embedding_prefix_enabled:
                meta.setdefault("embedding_context_prefix_enabled", True)
            chunk_id = _safe_uuid(meta.get("chunk_id")) or uuid.uuid4()
            meta["chunk_id"] = str(chunk_id)
            chunk_ids.append(chunk_id)
            normalized_chunks.append(
                ChunkInput(
                    content=c.content,
                    metadata=meta,
                    page_number=c.page_number,
                    start_char=c.start_char,
                    end_char=c.end_char,
                )
            )
            embed_text = _build_embedding_text(c.content or "", meta) if embedding_prefix_enabled else (c.content or "")
            vector_docs.append({"content": embed_text, "metadata": meta})
        
        # Run in parallel: vector indexing + PostgreSQL persistence.
        enable_vectors = self._resolve_chunk_vector_enabled(options)
        enable_bm25 = self._resolve_bm25_enabled(options)
        
        async def index_vectors_async():
            """Async vector indexing."""
            return await asyncio.to_thread(
                self._index_chunk_vectors,
                vector_docs,
                document_id=document_id,
                tenant_id=tenant_id,
                enable_vectors=enable_vectors,
            )
        
        async def persist_chunks_async():
            """Persist to PostgreSQL asynchronously."""
            return await asyncio.to_thread(
                self._persist_document_chunks,
                document_id=document_id,
                tenant_id=tenant_id,
                chunks=normalized_chunks,
                vector_ids=[],  # Set later.
                chunk_ids=chunk_ids,
                commit=commit,
            )
        
        # Run vector indexing and DB persistence concurrently.
        vector_ids, db_chunks = await asyncio.gather(
            index_vectors_async(),
            persist_chunks_async(),
            return_exceptions=True
        )
        
        # Handle exceptions.
        if isinstance(vector_ids, Exception):
            logger.error(f"Vector indexing failed: {vector_ids}")
            vector_ids = []
        
        if isinstance(db_chunks, Exception):
            logger.error(f"DB persistence failed: {db_chunks}")
            raise db_chunks
        
        # BM25 index update (independent, non-blocking).
        async def update_bm25_async():
            """Async BM25 update."""
            try:
                await asyncio.to_thread(
                    self._update_bm25_for_chunks,
                    db_chunks=db_chunks,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    default_source=default_source,
                    enable_bm25=enable_bm25,
                )
            except Exception as exc:
                logger.warning("Failed to update BM25 index incrementally: %s", exc)
        
        # Start BM25 update task (fire-and-forget).
        asyncio.create_task(update_bm25_async())

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

        entity_cache: Dict[Tuple[str, str, str], KgEntity] = {}
        db_events: List[KgSourceEvent] = []

        for item in events:
            event_obj = KgSourceEvent(
                tenant_id=tenant_id,
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                title=item.title,
                summary=item.summary,
                content=item.content,
                content_vector=item.vector,
                references=item.references,
                extra_data=item.extra_data,
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
                    KgEventEntity(
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
            logger.warning("Failed to delete vectors: %s", exc)

        try:
            hybrid_retriever.remove_document_from_bm25_index(document_id, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("Failed to update BM25 index after deletion: %s", exc)

    def delete_chunk_indexes_for_doc_pipeline_key(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        doc_pipeline_key: str,
    ) -> None:
        """
        Best-effort scoped delete for versioned documents.

        This avoids wiping the currently active pipeline when a *new* pipeline version
        is cancelled/failed mid-ingest.
        """
        filter_spec = {"doc_pipeline_key": {"$eq": str(doc_pipeline_key or "")}}
        try:
            get_vector_store().delete_by_document_id_and_filter(
                document_id=document_id,
                tenant_id=tenant_id,
                metadata_filter=filter_spec,
            )
        except NotImplementedError:
            logger.warning("Vector backend does not support selective delete; skipping scoped vector cleanup")
        except Exception as exc:
            logger.warning("Failed to delete vectors (scoped): %s", str(exc)[:200])

        try:
            hybrid_retriever.remove_from_bm25_index_by_metadata_filter(
                tenant_id=tenant_id,
                metadata_filter=filter_spec,
            )
        except Exception as exc:
            logger.warning("Failed to update BM25 index after scoped deletion: %s", str(exc)[:200])

    def delete_event_indexes(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        commit: bool = True,
        prune_orphan_entities: bool = False,
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
        )

    def delete_event_indexes_for_chunks(
        self,
        *,
        tenant_id: UUID,
        chunk_ids: Sequence[UUID],
        commit: bool = True,
        exclude_event_ids: Optional[Sequence[UUID]] = None,
        prune_orphan_entities: bool = False,
    ) -> dict[str, int]:
        """
        Delete KG events (and vectors) for a set of chunk_ids.

        This is primarily used to make KG extraction idempotent when re-running
        on the same chunks (avoid duplicate events).
        """
        chunk_ids_norm = [cid for cid in (_safe_uuid(x) for x in chunk_ids) if cid is not None]
        if not chunk_ids_norm:
            return {"events_deleted": 0, "entities_pruned": 0}

        query = self._db.query(KgSourceEvent).filter(
            KgSourceEvent.tenant_id == tenant_id,
            KgSourceEvent.chunk_id.in_(chunk_ids_norm),
        )
        if exclude_event_ids:
            exclude_norm = [eid for eid in (_safe_uuid(x) for x in exclude_event_ids) if eid is not None]
            if exclude_norm:
                query = query.filter(~KgSourceEvent.id.in_(exclude_norm))

        return self._delete_event_indexes(
            tenant_id=tenant_id,
            query=query,
            commit=commit,
            prune_orphan_entities=prune_orphan_entities,
        )

    def prune_orphan_entities(
        self,
        *,
        tenant_id: UUID,
        entity_ids: Optional[Sequence[UUID]] = None,
        commit: bool = True,
    ) -> int:
        """
        Delete KG entities (and vectors) that have no remaining KgEventEntity links.

        When `entity_ids` is provided, pruning is scoped to that candidate set.
        """
        q = (
            self._db.query(KgEntity.id)
            .outerjoin(KgEventEntity, KgEventEntity.entity_id == KgEntity.id)
            .filter(KgEntity.tenant_id == tenant_id)
            .filter(KgEventEntity.entity_id.is_(None))
        )
        if entity_ids:
            entity_ids_norm = [eid for eid in (_safe_uuid(x) for x in entity_ids) if eid is not None]
            if entity_ids_norm:
                q = q.filter(KgEntity.id.in_(entity_ids_norm))
            else:
                return 0

        orphan_ids = [row[0] for row in q.all() if row and row[0]]
        if not orphan_ids:
            return 0

        try:
            self._entity_vector.delete([str(eid) for eid in orphan_ids])
        except Exception as exc:
            logger.warning("Failed to delete KG entity vectors: %s", exc)

        self._db.query(KgEntity).filter(KgEntity.id.in_(orphan_ids)).delete(synchronize_session=False)
        if commit:
            self._db.commit()
        else:
            self._db.flush()
        return len(orphan_ids)

    def _delete_event_indexes(
        self,
        *,
        tenant_id: UUID,
        query,
        commit: bool,
        prune_orphan_entities: bool,
    ) -> dict[str, int]:
        event_ids = [row[0] for row in query.with_entities(KgSourceEvent.id).all() if row and row[0]]
        if not event_ids:
            return {"events_deleted": 0, "entities_pruned": 0}

        candidate_entity_ids: list[UUID] = []
        if prune_orphan_entities:
            candidate_entity_ids = [
                row[0]
                for row in (
                    self._db.query(KgEventEntity.entity_id)
                    .filter(KgEventEntity.event_id.in_(event_ids))
                    .distinct()
                    .all()
                )
                if row and row[0]
            ]

        try:
            self._event_vector.delete([str(ev_id) for ev_id in event_ids])
        except Exception as exc:
            logger.warning("Failed to delete KG event vectors: %s", exc)

        deleted = int(query.delete(synchronize_session=False) or 0)
        if commit:
            self._db.commit()
        else:
            self._db.flush()

        pruned = 0
        if prune_orphan_entities and candidate_entity_ids:
            pruned = int(self.prune_orphan_entities(tenant_id=tenant_id, entity_ids=candidate_entity_ids, commit=commit))

        return {"events_deleted": deleted, "entities_pruned": pruned}

    def rebuild_chunk_indexes(
        self,
        *,
        tenant_id: UUID,
        document_ids: Optional[List[UUID]] = None,
    ) -> None:
        if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
            return
        count = hybrid_retriever.build_bm25_index_from_db(
            self._db,
            tenant_id=tenant_id,
            document_ids=document_ids,
            max_chunks=0,
            batch_size=2000,
        )
        if not count:
            logger.warning("No chunks found for BM25 index")
            return

    def rebuild_event_indexes(
        self,
        *,
        tenant_id: UUID,
        document_ids: Optional[List[UUID]] = None,
    ) -> None:
        event_query = self._db.query(KgSourceEvent).filter(KgSourceEvent.tenant_id == tenant_id)
        if document_ids:
            event_query = event_query.filter(KgSourceEvent.document_id.in_(document_ids))
        events = event_query.all()
        if events and bool(getattr(settings, "EVENT_VECTOR_ENABLED", True)):
            self._index_event_vectors(events)

        event_ids = [ev.id for ev in events]
        if not event_ids:
            return

        entity_id_rows = (
            self._db.query(KgEventEntity.entity_id)
            .filter(KgEventEntity.event_id.in_(event_ids))
            .distinct()
            .all()
        )
        entity_ids = [row[0] for row in entity_id_rows if row and row[0]]
        if not entity_ids:
            return

        entities = (
            self._db.query(KgEntity)
            .filter(KgEntity.tenant_id == tenant_id, KgEntity.id.in_(entity_ids))
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
            extra_data=record.extra_data,
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
            batch_size = int(getattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256) or 256)
            max_retries = int(getattr(settings, "VECTOR_WRITE_MAX_RETRIES", 1) or 1)
            backoff = float(getattr(settings, "VECTOR_WRITE_RETRY_BACKOFF_SEC", 0.5) or 0.5)

            out: List[Optional[str]] = []
            for i in range(0, len(docs), batch_size):
                batch = docs[i : i + batch_size]
                last_exc: Optional[Exception] = None
                for attempt in range(max_retries + 1):
                    try:
                        out.extend(list(vector_store.add_documents(batch, document_id, tenant_id)))
                        last_exc = None
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        if attempt < max_retries:
                            log_metrics(
                                {
                                    "event": "ingest.vector_write.retry",
                                    "tenant_id": str(tenant_id),
                                    "document_id": str(document_id),
                                    "attempt": attempt + 1,
                                    "max_retries": max_retries + 1,
                                    "batch_size": len(batch),
                                    "backoff_sec": round(float(backoff), 3),
                                    "error": str(exc)[:200],
                                }
                            )
                            logger.warning(
                                "Vector write failed (attempt %s/%s), retrying in %.2fs: %s",
                                attempt + 1,
                                max_retries + 1,
                                backoff,
                                str(exc)[:200],
                            )
                            time.sleep(backoff)
                            backoff *= 2
                        else:
                            raise

                if last_exc is not None:
                    raise last_exc

            if len(out) != len(docs):
                raise ValueError(f"vector ids length {len(out)} != docs length {len(docs)}")
            return out
        except Exception as exc:
            logger.warning("Failed to store vectors: %s", exc)
            logger.warning("Proceeding without vector ids; BM25-only retrieval will still work.")
            return [None] * len(docs)

    def _persist_document_chunks(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        chunks: List[ChunkInput],
        vector_ids: Optional[List[Optional[str]]] = None,
        chunk_ids: Optional[List[UUID]] = None,
        commit: bool = True,
    ) -> List[DocumentChunk]:
        if not chunks:
            return []

        if vector_ids is None:
            vector_ids = [None] * len(chunks)
        if len(vector_ids) != len(chunks):
            raise ValueError(f"vector_ids length {len(vector_ids)} != chunks length {len(chunks)}")

        if chunk_ids is None:
            chunk_ids = [uuid.uuid4() for _ in chunks]
        if len(chunk_ids) != len(chunks):
            raise ValueError(f"chunk_ids length {len(chunk_ids)} != chunks length {len(chunks)}")

        db_chunks: List[DocumentChunk] = []
        for idx, (chunk, vector_id, chunk_id) in enumerate(zip(chunks, vector_ids, chunk_ids)):
            meta = dict(chunk.metadata or {})
            normalize_image_metadata(meta)
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("chunk_index", idx)
            # Versioning: keep a stable composite key so retrieval can filter the active
            # pipeline per document across multi-doc queries.
            pipeline_hash = str(meta.get("pipeline_hash") or "").strip()
            if pipeline_hash:
                meta.setdefault("doc_pipeline_key", f"{document_id}:{pipeline_hash}")
            meta = _ensure_chunk_metadata(meta, content=chunk.content or "", document_id=document_id, chunk_index=idx)
            meta["chunk_id"] = str(chunk_id)
            page_number = (
                _safe_int(chunk.page_number)
                if chunk.page_number is not None
                else _safe_int(meta.get("page") or meta.get("page_number"))
            )
            start_char = _safe_int(chunk.start_char) if chunk.start_char is not None else _safe_int(meta.get("start_char"))
            end_char = _safe_int(chunk.end_char) if chunk.end_char is not None else _safe_int(meta.get("end_char"))

            db_chunks.append(
                DocumentChunk(
                    id=chunk_id,
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
            normalize_image_metadata(meta)
            meta = _ensure_chunk_metadata(
                meta,
                content=db_chunk.content or "",
                document_id=document_id,
                chunk_index=int(db_chunk.chunk_index or 0),
            )
            meta.setdefault("index_kind", IndexKind.CHUNK.value)
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("chunk_index", db_chunk.chunk_index)
            meta.setdefault("chunk_id", str(db_chunk.id))
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

    def _index_event_vectors(self, events: Iterable[KgSourceEvent]) -> List[str]:
        items: List[Dict[str, Any]] = []
        embeddings: List[List[float]] = []
        for ev in events:
            if not ev.content_vector:
                continue
            refs = ev.references if isinstance(getattr(ev, "references", None), dict) else {}
            embeddings.append(list(ev.content_vector))
            meta: Dict[str, Any] = {
                "tenant_id": str(ev.tenant_id),
                "document_id": str(ev.document_id) if ev.document_id else "",
                "chunk_id": str(ev.chunk_id) if ev.chunk_id else "",
                "title": ev.title,
                "summary": ev.summary,
                "index_kind": IndexKind.EVENT.value,
            }
            if isinstance(refs, dict):
                for k in (
                    "chunk_index",
                    "page",
                    "start_char",
                    "end_char",
                    "chunk_key",
                    "content_hash",
                    "content_len",
                    "source",
                ):
                    v = refs.get(k)
                    if v is None:
                        continue
                    meta[k] = v
            items.append(
                {
                    "id": str(ev.id),
                    "content": ev.content,
                    "metadata": meta,
                }
            )

        if not items:
            return []
        try:
            return self._event_vector.add_vectors(items, embeddings=embeddings)
        except Exception as exc:
            logger.warning("Failed to store KG event vectors: %s", exc)
            return []

    def _index_entity_vectors(self, entities: Iterable[KgEntity]) -> List[str]:
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
