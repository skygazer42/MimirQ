"""Owned chunks operations for indexing."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langchain_core.documents import Document as LCDocument
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dataset import Dataset as DBDataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.query.normalize import normalize_query
from app.rag.chunking.utils.hierarchical import apply_sequence_hierarchy_metadata
from app.rag.core.metadata import normalize_image_metadata
from app.rag.retrieval.corpus_index import CorpusScope, get_corpus_index
from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig
from app.services.document_index_channel_service import (
    DOCUMENT_INDEX_CHANNEL_DISABLED,
    DOCUMENT_INDEX_CHANNEL_ERROR,
    DOCUMENT_INDEX_CHANNEL_PROCESSING,
    DOCUMENT_INDEX_CHANNEL_READY,
)
from app.services.indexing.chunk_preparation import (
    _build_contextual_prefix_for_chunk,
    _build_embedding_text,
    _chunk_index_content,
    _chunk_position_values,
    _derive_document_title,
    _document_chunk_metadata,
    _ensure_chunk_metadata,
    _extract_heading_for_embedding,
    _extract_title_for_embedding,
    _normalized_chunk_ids,
    _normalized_vector_ids,
    _safe_uuid,
    _should_apply_contextual_retrieval_prefix,
    _should_prefix_embedding,
)
from app.services.indexing.quota import _enforce_embedding_quota_gate
from app.services.indexing.tracking import (
    _INDEXER_FALLBACK_LOG_MESSAGE,
    load_document_for_channel_tracking,
    track_document_channel,
)
from app.services.indexing.vector_writer import (
    ChunkVectorWriter,
    DatasetScopedEmbeddingRuntimeResolutionError,
    dataset_scoped_runtime_unavailable,
)
from app.types.indexing import (
    ChunkInput,
    IndexingOptions,
    IndexKind,
    IndexScope,
    PersistChunksResult,
)

logger = logging.getLogger("indexer")


@dataclass(frozen=True)
class ChunkIndexContext:
    embedding_runtime: DatasetEmbeddingRuntimeConfig
    document: DBDocument
    document_title: str | None
    retrieval_metadata: dict[str, Any]


@dataclass(frozen=True)
class ChunkEmbeddingFlags:
    embedding_prefix_enabled: bool
    contextual_retrieval_enabled: bool
    contextual_retrieval_lazy_mode: bool
    field_aware_enabled: bool


class ChunkIndexer:
    """Own the chunk write operation and its corpus/channel transitions."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._vectors = ChunkVectorWriter(db)

    def _resolve_chunk_vector_enabled(self, options: IndexingOptions | None) -> bool:
        if options and options.chunk_vector_enabled is not None:
            return bool(options.chunk_vector_enabled)
        return settings.CHUNK_VECTOR_ENABLED

    def _resolve_bm25_enabled(self, options: IndexingOptions | None) -> bool:
        if options and options.bm25_index_enabled is not None:
            return bool(options.bm25_index_enabled)
        return settings.BM25_INDEX_ENABLED

    def _resolve_chunk_index_context(self, *, tenant_id: UUID, document_id: UUID) -> ChunkIndexContext:
        try:
            runtime = self._vectors.resolve_document_runtime(tenant_id=tenant_id, document_id=document_id)
            document = load_document_for_channel_tracking(self._db, tenant_id=tenant_id, document_id=document_id)
            if document is None:
                raise dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id)
            metadata = document.doc_metadata
            return ChunkIndexContext(
                embedding_runtime=runtime,
                document=document,
                document_title=_derive_document_title(document.filename, metadata),
                retrieval_metadata=dict(metadata) if metadata is not None else {},
            )
        except (ValueError, DatasetScopedEmbeddingRuntimeResolutionError):
            raise
        except Exception as exc:
            raise dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id) from exc

    def _chunk_index_option_flags(self, options: IndexingOptions | None) -> ChunkEmbeddingFlags:
        return ChunkEmbeddingFlags(
            embedding_prefix_enabled=bool(options and options.embedding_context_prefix_enabled),
            contextual_retrieval_enabled=bool(options and options.embedding_contextual_retrieval_enabled),
            contextual_retrieval_lazy_mode=bool(options and options.embedding_contextual_retrieval_lazy_mode),
            field_aware_enabled=bool(options and options.embedding_field_aware_enabled),
        )

    def _prepare_chunk_index_inputs(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        chunks: Sequence[ChunkInput],
        source: str,
        context: ChunkIndexContext,
        flags: ChunkEmbeddingFlags,
    ) -> list[tuple[ChunkInput, dict[str, Any], UUID]]:
        prepared_chunks: list[tuple[ChunkInput, dict[str, Any], UUID]] = []
        embedding_runtime = context.embedding_runtime
        total_chunks = len(chunks)
        for idx, chunk in enumerate(chunks):
            meta = dict(chunk.metadata)
            meta.setdefault("index_kind", IndexKind.CHUNK.value)
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("document_id", str(document_id))
            meta.setdefault("embedding_space_hash", context.embedding_runtime.embedding_space_hash)
            meta.setdefault("dataset_scoped", bool(embedding_runtime.dataset_scoped))
            if embedding_runtime.dataset_scoped:
                meta.setdefault("vector_collection_name", embedding_runtime.collection_name)
            if context.document.dataset_id is not None:
                meta.setdefault("dataset_id", str(context.document.dataset_id))
            meta.setdefault("source", source)
            if context.document.file_type and not meta.get("file_type"):
                meta["file_type"] = context.document.file_type
            if context.document_title and not meta.get("document_title"):
                meta["document_title"] = context.document_title
            for metadata_key in ("document_keywords", "document_questions"):
                value = context.retrieval_metadata.get(metadata_key)
                if value not in (None, "", [], {}) and meta.get(metadata_key) in (None, "", [], {}):
                    meta[metadata_key] = value
            for flag_name, enabled in (
                ("embedding_prefix_enabled", flags.embedding_prefix_enabled),
                ("contextual_retrieval_enabled", flags.contextual_retrieval_enabled),
                ("contextual_retrieval_lazy_mode", flags.contextual_retrieval_lazy_mode),
                ("field_aware_enabled", flags.field_aware_enabled),
            ):
                if enabled:
                    meta.setdefault(flag_name, True)
            meta = _ensure_chunk_metadata(
                meta,
                content=chunk.content or "",
                document_id=document_id,
                chunk_index=idx,
                total_chunks=total_chunks,
            )
            chunk_id = _safe_uuid(meta.get("chunk_id")) or uuid.uuid4()
            meta["chunk_id"] = str(chunk_id)
            prepared_chunks.append((chunk, meta, chunk_id))
        apply_sequence_hierarchy_metadata(
            [meta for _, meta, _ in prepared_chunks],
            document_id=str(document_id),
            basis="chunk_sequence",
            level="chunk",
        )
        return prepared_chunks

    def _chunk_embed_text(
        self,
        *,
        raw_body: str,
        embed_text: str,
        meta: dict[str, Any],
        document_title: str | None,
        flags: ChunkEmbeddingFlags,
    ) -> str:
        if (
            flags.contextual_retrieval_enabled
            and raw_body
            and _should_prefix_embedding(meta)
            and _should_apply_contextual_retrieval_prefix(meta, lazy_mode=flags.contextual_retrieval_lazy_mode)
        ):
            try:
                title = document_title or _extract_title_for_embedding(meta)
                prefix = _build_contextual_prefix_for_chunk(
                    raw_body=raw_body,
                    document_title=title,
                    meta=meta,
                )
                if prefix:
                    embed_text = prefix + "\n" + embed_text
            except Exception as exc:
                logger.debug("Failed to build contextual embedding prefix; continuing without prefix: %s", exc)
        if flags.embedding_prefix_enabled:
            embed_text = _build_embedding_text(embed_text, meta)
        return normalize_query(embed_text).normalized_text

    def _chunk_extra_vector_docs(
        self, *, meta: dict[str, Any], chunk_id: UUID, field_aware_enabled: bool
    ) -> list[dict[str, Any]]:
        if not field_aware_enabled or not _should_prefix_embedding(meta):
            return []
        out: list[dict[str, Any]] = []
        title = _extract_title_for_embedding(meta)
        if title:
            meta_t = dict(meta)
            meta_t["chunk_id"] = f"{chunk_id}:title"
            out.append({"content": normalize_query(f"[Title] {title}").normalized_text, "metadata": meta_t})
        heading = _extract_heading_for_embedding(meta)
        if heading:
            meta_h = dict(meta)
            meta_h["chunk_id"] = f"{chunk_id}:heading"
            out.append({"content": normalize_query(f"[Heading] {heading}").normalized_text, "metadata": meta_h})
        return out

    def _build_chunk_vector_payloads(
        self,
        *,
        prepared_chunks: list[tuple[ChunkInput, dict[str, Any], UUID]],
        document_title: str | None,
        flags: ChunkEmbeddingFlags,
    ) -> tuple[list[ChunkInput], list[dict[str, Any]], list[dict[str, Any]], list[UUID]]:
        normalized_chunks: Sequence[ChunkInput] = []
        vector_docs: list[dict[str, Any]] = []
        extra_vector_docs: list[dict[str, Any]] = []
        chunk_ids: list[UUID] = []
        for chunk, meta, chunk_id in prepared_chunks:
            chunk_ids.append(chunk_id)
            raw_body = chunk.content or ""
            embed_text, normalized_meta = _chunk_index_content(raw_body, meta)
            normalized_chunks.append(
                ChunkInput(
                    content=chunk.content,
                    metadata=normalized_meta,
                    page_number=chunk.page_number,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                )
            )
            vector_docs.append(
                {
                    "content": self._chunk_embed_text(
                        raw_body=raw_body,
                        embed_text=embed_text,
                        meta=normalized_meta,
                        document_title=document_title,
                        flags=flags,
                    ),
                    "metadata": normalized_meta,
                }
            )
            extra_vector_docs.extend(
                self._chunk_extra_vector_docs(
                    meta=normalized_meta,
                    chunk_id=chunk_id,
                    field_aware_enabled=flags.field_aware_enabled,
                )
            )
        return normalized_chunks, vector_docs, extra_vector_docs, chunk_ids

    def _index_chunk_vectors_with_tracking(
        self,
        *,
        context: ChunkIndexContext,
        document_id: UUID,
        tenant_id: UUID,
        vector_docs: list[dict[str, Any]],
        extra_vector_docs: list[dict[str, Any]],
        vector_enabled: bool,
    ) -> list[str]:
        track_document_channel(
            self._db,
            document=context.document,
            channel="vector",
            status=DOCUMENT_INDEX_CHANNEL_PROCESSING if vector_enabled else DOCUMENT_INDEX_CHANNEL_DISABLED,
            increment_attempt=vector_enabled,
        )
        try:
            vector_ids = self._vectors.upsert(
                vector_docs,
                document_id=document_id,
                tenant_id=tenant_id,
                enable_vectors=vector_enabled,
                embedding_runtime=context.embedding_runtime,
            )
        except Exception as exc:
            track_document_channel(
                self._db,
                document=context.document,
                channel="vector",
                status=DOCUMENT_INDEX_CHANNEL_ERROR,
                error=str(exc)[:2000],
            )
            raise
        if extra_vector_docs and vector_enabled:
            try:
                self._vectors.upsert(
                    extra_vector_docs,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    enable_vectors=True,
                    embedding_runtime=context.embedding_runtime,
                )
            except Exception as exc:
                logger.debug(_INDEXER_FALLBACK_LOG_MESSAGE, exc)
        track_document_channel(
            self._db,
            document=context.document,
            channel="vector",
            status=DOCUMENT_INDEX_CHANNEL_READY if vector_enabled else DOCUMENT_INDEX_CHANNEL_DISABLED,
        )
        return vector_ids

    def _update_bm25_with_tracking(
        self,
        *,
        context: ChunkIndexContext,
        db_chunks: list[DocumentChunk],
        tenant_id: UUID,
        document_id: UUID,
        default_source: str,
        bm25_enabled: bool,
    ) -> None:
        track_document_channel(
            self._db,
            document=context.document,
            channel="bm25",
            status=DOCUMENT_INDEX_CHANNEL_PROCESSING if bm25_enabled else DOCUMENT_INDEX_CHANNEL_DISABLED,
            increment_attempt=bm25_enabled,
        )
        try:
            self.sync_corpus(
                db_chunks=db_chunks,
                tenant_id=tenant_id,
                document_id=document_id,
                default_source=default_source,
                enable_bm25=bm25_enabled,
            )
        except Exception as exc:
            track_document_channel(
                self._db,
                document=context.document,
                channel="bm25",
                status=DOCUMENT_INDEX_CHANNEL_ERROR if bm25_enabled else DOCUMENT_INDEX_CHANNEL_DISABLED,
                error=str(exc)[:2000] if bm25_enabled else None,
            )
            logger.warning("Failed to update BM25 index incrementally: %s", exc)
            return
        track_document_channel(
            self._db,
            document=context.document,
            channel="bm25",
            status=DOCUMENT_INDEX_CHANNEL_READY if bm25_enabled else DOCUMENT_INDEX_CHANNEL_DISABLED,
        )

    def index(
        self,
        *,
        scope: IndexScope,
        chunks: Sequence[ChunkInput],
        default_source: str = "unknown",
        commit: bool = True,
        options: IndexingOptions | None = None,
    ) -> PersistChunksResult:
        tenant_id, document_id = scope.tenant_id, scope.document_id
        if document_id is None:
            raise ValueError("Chunk indexing requires document_id")
        context = self._resolve_chunk_index_context(tenant_id=tenant_id, document_id=document_id)
        source = str(default_source or "").strip() or "unknown"
        total_characters = sum(len(c.content) for c in chunks)
        vector_enabled = self._resolve_chunk_vector_enabled(options)
        bm25_enabled = self._resolve_bm25_enabled(options)
        _enforce_embedding_quota_gate(
            self._db,
            tenant_id=tenant_id,
            document_id=document_id,
            additional_chars=total_characters,
        )
        flags = self._chunk_index_option_flags(options)
        prepared_chunks = self._prepare_chunk_index_inputs(
            document_id=document_id,
            tenant_id=tenant_id,
            chunks=chunks,
            source=source,
            context=context,
            flags=flags,
        )
        normalized_chunks, vector_docs, extra_vector_docs, chunk_ids = self._build_chunk_vector_payloads(
            prepared_chunks=prepared_chunks,
            document_title=context.document_title,
            flags=flags,
        )
        vector_ids = self._index_chunk_vectors_with_tracking(
            context=context,
            document_id=document_id,
            tenant_id=tenant_id,
            vector_docs=vector_docs,
            extra_vector_docs=extra_vector_docs,
            vector_enabled=vector_enabled,
        )
        try:
            db_chunks = self._persist_document_chunks(
                document_id=document_id,
                tenant_id=tenant_id,
                dataset_id=context.document.dataset_id,
                chunks=normalized_chunks,
                vector_ids=vector_ids,
                chunk_ids=chunk_ids,
                commit=commit,
            )
        except Exception:
            if vector_enabled:
                try:
                    self._vectors.cleanup_attempted_chunks(
                        [*vector_docs, *extra_vector_docs],
                        document_id=document_id,
                        tenant_id=tenant_id,
                        runtime=context.embedding_runtime,
                    )
                except Exception as cleanup_error:
                    logger.warning(
                        "Failed to clean attempted chunk vectors after persistence failure: %s", cleanup_error
                    )
            raise
        self._update_bm25_with_tracking(
            context=context,
            db_chunks=db_chunks,
            tenant_id=tenant_id,
            document_id=document_id,
            default_source=default_source,
            bm25_enabled=bm25_enabled,
        )

        return PersistChunksResult(
            db_chunks=db_chunks,
            chunk_ids=[c.id for c in db_chunks],
            vector_ids=vector_ids,
            total_characters=total_characters,
        )

    def delete_chunk_indexes(self, *, tenant_id: UUID, document_id: UUID, strict: bool = False) -> None:
        failures: list[Exception] = []
        try:
            self._vectors._delete_dataset_scoped_chunk_vectors(tenant_id=tenant_id, document_id=document_id)
        except Exception as exc:
            logger.warning("Failed to delete dataset-scoped vectors: %s", exc)
            failures.append(exc)

        try:
            self._vectors.delete_default(document_id=document_id, tenant_id=tenant_id)
        except Exception as exc:
            logger.warning("Failed to delete vectors: %s", exc)
            failures.append(exc)

        try:
            get_corpus_index().remove(tenant_id=tenant_id, metadata_filter={"document_id": str(document_id)})
        except Exception as exc:
            logger.warning("Failed to update BM25 index after deletion: %s", exc)
            failures.append(exc)

        try:
            self._touch_chunk_retrieval_scope(tenant_id=tenant_id, document_id=document_id)
            self._db.flush()
        except Exception as exc:
            logger.warning("Failed to touch retrieval scope after deletion: %s", exc)
            failures.append(exc)

        if strict and failures:
            raise RuntimeError("Document index cleanup failed") from failures[0]

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
            self._vectors._delete_dataset_scoped_chunk_vectors(
                tenant_id=tenant_id,
                document_id=document_id,
                metadata_filter=filter_spec,
            )
        except Exception as exc:
            logger.warning("Failed to delete dataset-scoped vectors (scoped): %s", str(exc)[:200])

        try:
            self._vectors.delete_default(
                document_id=document_id,
                tenant_id=tenant_id,
                metadata_filter=filter_spec,
            )
        except NotImplementedError:
            logger.warning("Vector backend does not support selective delete; skipping scoped vector cleanup")
        except Exception as exc:
            logger.warning("Failed to delete vectors (scoped): %s", str(exc)[:200])

        try:
            get_corpus_index().remove(tenant_id=tenant_id, metadata_filter=filter_spec)
        except Exception as exc:
            logger.warning("Failed to update BM25 index after scoped deletion: %s", str(exc)[:200])

        try:
            self._touch_chunk_retrieval_scope(tenant_id=tenant_id, document_id=document_id)
            self._db.flush()
        except Exception as exc:
            logger.warning("Failed to touch retrieval scope after scoped deletion: %s", str(exc)[:200])

    def rebuild_chunk_indexes(
        self,
        *,
        tenant_id: UUID,
        document_ids: list[UUID] | None = None,
    ) -> None:
        if not settings.BM25_INDEX_ENABLED:
            return
        count = get_corpus_index().rebuild(
            self._db, scope=CorpusScope(tenant_id=tenant_id, document_ids=tuple(document_ids or ())), batch_size=2000
        )
        if not count:
            logger.warning("No chunks found for BM25 index")
            return
        if document_ids:
            for document_id in list(dict.fromkeys(document_ids)):
                self._touch_chunk_retrieval_scope(tenant_id=tenant_id, document_id=document_id)
            self._db.flush()

    def _touch_chunk_retrieval_scope(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        dataset_id: UUID | None = None,
    ) -> None:
        now = datetime.now(UTC)
        document = (
            self._db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id == document_id).first()
        )
        resolved_dataset_id = dataset_id
        if document is not None:
            document.updated_at = now
            if resolved_dataset_id is None:
                resolved_dataset_id = document.dataset_id
        if resolved_dataset_id is None:
            return
        dataset = (
            self._db.query(DBDataset)
            .filter(DBDataset.tenant_id == tenant_id, DBDataset.id == resolved_dataset_id)
            .first()
        )
        if dataset is not None:
            dataset.updated_at = now

    def _persist_document_chunks(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        dataset_id: UUID | None = None,
        chunks: Sequence[ChunkInput],
        vector_ids: list[str | None] | None = None,
        chunk_ids: list[UUID] | None = None,
        commit: bool = True,
    ) -> list[DocumentChunk]:
        if not chunks:
            return []

        vector_ids = _normalized_vector_ids(vector_ids, chunks_count=len(chunks))
        chunk_ids = _normalized_chunk_ids(chunk_ids, chunks_count=len(chunks))
        db_chunks: list[DocumentChunk] = []
        total_chunks = len(chunks)
        for idx, (chunk, vector_id, chunk_id) in enumerate(zip(chunks, vector_ids, chunk_ids, strict=False)):
            meta = _document_chunk_metadata(
                chunk,
                document_id=document_id,
                tenant_id=tenant_id,
                chunk_index=idx,
                total_chunks=total_chunks,
                chunk_id=chunk_id,
            )
            page_number, start_char, end_char = _chunk_position_values(chunk, meta)

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
        self._touch_chunk_retrieval_scope(
            tenant_id=tenant_id,
            document_id=document_id,
            dataset_id=dataset_id,
        )
        self._db.flush()
        if commit:
            self._db.commit()

        return db_chunks

    def sync_corpus(
        self,
        *,
        db_chunks: list[DocumentChunk],
        tenant_id: UUID,
        document_id: UUID,
        default_source: str = "unknown",
        enable_bm25: bool,
    ) -> None:
        if not db_chunks:
            return
        if not enable_bm25:
            return

        bm25_docs: list[LCDocument] = []
        total_chunks = len(db_chunks)
        for db_chunk in db_chunks:
            meta = dict(db_chunk.doc_metadata or {})
            normalize_image_metadata(meta)
            meta = _ensure_chunk_metadata(
                meta,
                content=db_chunk.content or "",
                document_id=document_id,
                chunk_index=int(db_chunk.chunk_index or 0),
                total_chunks=total_chunks,
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
            page_content, meta = _chunk_index_content(db_chunk.content or "", meta)
            bm25_docs.append(LCDocument(page_content=page_content, id=str(db_chunk.id), metadata=meta))

        get_corpus_index().upsert(self._db, tenant_id=tenant_id, documents=bm25_docs)
