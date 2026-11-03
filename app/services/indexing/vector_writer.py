"""Owned vector writer operations for indexing."""

import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.models.dataset import Dataset as DBDataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.embedding import create_langchain_embeddings_from_config
from app.rag.embedding.utils import embedding_space_hash_for_config
from app.services.dataset_embedding_config import (
    DatasetEmbeddingRuntimeConfig,
    collection_name_for_embedding_space,
    create_embeddings_for_runtime,
    resolve_dataset_embedding_runtime,
)
from app.services.metrics_logger import log_metrics
from app.storage.vector.factory import get_vector_store
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

logger = logging.getLogger("indexer")

_CHUNK_METADATA_SCAN_BATCH_SIZE = 256
_shadow_vector_writer_sig: str | None = None
_shadow_vector_writer: tuple[Any, Any, str] | None = None
_SHADOW_VECTOR_WRITE_EVENT = "ingest.shadow_vector_write"


class DatasetScopedEmbeddingRuntimeResolutionError(RuntimeError):
    """Raised when a dataset-scoped document cannot safely resolve its embedding runtime."""


def dataset_scoped_runtime_unavailable(
    *, document_id: UUID, tenant_id: UUID
) -> DatasetScopedEmbeddingRuntimeResolutionError:
    return DatasetScopedEmbeddingRuntimeResolutionError(
        "dataset-scoped embedding runtime unavailable during indexing "
        f"(tenant_id={tenant_id}, document_id={document_id})"
    )


def milvus_backend_enabled() -> bool:
    return settings.VECTOR_BACKEND.strip().lower() == "milvus"


def _shadow_vector_config() -> tuple[str, str, str, str, str] | None:
    if not settings.EMBEDDING_SHADOW_ENABLED:
        return None
    if not milvus_backend_enabled():
        return None

    shadow_collection = settings.MILVUS_SHADOW_COLLECTION_NAME.strip()
    shadow_model = settings.EMBEDDING_SHADOW_MODEL.strip()
    if not shadow_collection or not shadow_model:
        return None

    provider_raw = (
        settings.EMBEDDING_SHADOW_PROVIDER.strip().lower()
        or (settings.EMBEDDING_PROVIDER or "openai_compatible").strip().lower()
    )
    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider_raw, "openai_compatible")
    api_key = (
        settings.EMBEDDING_SHADOW_API_KEY.strip() or settings.EMBEDDING_API_KEY.strip() or settings.LLM_API_KEY.strip()
    )
    base_url = (
        settings.EMBEDDING_SHADOW_API_BASE.strip()
        or settings.EMBEDDING_API_BASE.strip()
        or settings.LLM_API_BASE.strip()
    )
    return mapped_provider, shadow_model, api_key, base_url, shadow_collection


def _cache_shadow_vector_writer(
    sig: str,
    writer: tuple[Any, Any, str] | None,
) -> tuple[Any, Any, str] | None:
    global _shadow_vector_writer_sig, _shadow_vector_writer
    _shadow_vector_writer_sig = sig
    _shadow_vector_writer = writer
    return writer


def _shadow_embedding_space_hash(*, provider: str, model: str, base_url: str) -> str:
    return embedding_space_hash_for_config(
        provider=provider,
        model=model,
        base_url=base_url,
        length=16,
    )


def _resolve_shadow_vector_writer() -> tuple[Any, Any, str] | None:
    """
    Best-effort resolve (embeddings, milvus_adapter, shadow_space_hash) for dual-write.

    This is used by Gap5 embedding blue-green migrations: when enabled, ingestion writes
    vectors into both the primary collection (settings.MILVUS_COLLECTION_NAME) and the
    shadow collection (settings.MILVUS_SHADOW_COLLECTION_NAME) using a potentially
    different embedding model.
    """
    config = _shadow_vector_config()
    if config is None:
        return None
    mapped_provider, shadow_model, api_key, base_url, shadow_collection = config
    sig = f"{mapped_provider}|{shadow_model}|{base_url}|{shadow_collection}"

    if _shadow_vector_writer is not None and _shadow_vector_writer_sig == sig:
        return _shadow_vector_writer

    try:
        emb = create_langchain_embeddings_from_config(
            provider=mapped_provider,
            model=shadow_model,
            api_key=api_key,
            base_url=base_url,
            dimension=None,  # Auto-detect
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shadow embeddings init failed; dual-write disabled: %s", str(exc)[:200])
        return _cache_shadow_vector_writer(sig, None)

    try:
        adapter = get_milvus_adapter(resolve_collection_name(shadow_collection))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shadow Milvus adapter init failed; dual-write disabled: %s", str(exc)[:200])
        return _cache_shadow_vector_writer(sig, None)

    try:
        shadow_space = _shadow_embedding_space_hash(provider=mapped_provider, model=shadow_model, base_url=base_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shadow embedding-space hash failed; dual-write disabled: %s", type(exc).__name__)
        return _cache_shadow_vector_writer(sig, None)
    return _cache_shadow_vector_writer(sig, (emb, adapter, shadow_space))


def _prepare_shadow_vector_items(
    docs: list[dict[str, Any]],
    *,
    shadow_space: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    texts: list[str] = []
    for doc in docs:
        meta0 = doc.get("metadata") if isinstance(doc, dict) else None
        meta = dict(meta0 or {}) if isinstance(meta0, dict) else {}
        chunk_id = str(meta.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        content = str(doc.get("content") or "")
        meta["embedding_space_hash"] = shadow_space
        items.append({"id": chunk_id, "content": content, "metadata": meta})
        texts.append(content)
    return items, texts


def _log_shadow_vector_write(
    *,
    ok: bool,
    tenant_id: UUID,
    document_id: UUID,
    count: int,
    reason: str | None = None,
    error: Exception | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": _SHADOW_VECTOR_WRITE_EVENT,
        "ok": ok,
        "tenant_id": str(tenant_id),
        "document_id": str(document_id),
        "count": int(count),
    }
    if reason:
        payload["reason"] = reason
    if error is not None:
        payload["error"] = str(error)[:200]
    log_metrics(payload)


def dual_write_shadow_vectors_best_effort(
    docs: list[dict[str, Any]],
    *,
    document_id: UUID,
    tenant_id: UUID,
) -> None:
    writer = _resolve_shadow_vector_writer()
    if writer is None:
        return
    embeddings, adapter, shadow_space = writer

    if not docs:
        return

    items, texts = _prepare_shadow_vector_items(docs, shadow_space=shadow_space)
    if not items:
        return

    try:
        vecs = embeddings.embed_documents(texts)
    except Exception as exc:  # noqa: BLE001
        _log_shadow_vector_write(
            ok=False,
            reason="embed_failed",
            tenant_id=tenant_id,
            document_id=document_id,
            count=len(items),
            error=exc,
        )
        return

    try:
        batch_size = settings.VECTOR_WRITE_BATCH_SIZE or 256
        adapter.add_vectors(items, embeddings=vecs, batch_size=batch_size, upsert=True)
        _log_shadow_vector_write(ok=True, tenant_id=tenant_id, document_id=document_id, count=len(items))
    except Exception as exc:  # noqa: BLE001
        _log_shadow_vector_write(
            ok=False,
            reason="milvus_write_failed",
            tenant_id=tenant_id,
            document_id=document_id,
            count=len(items),
            error=exc,
        )
        return


def _vector_write_batch_size() -> int:
    return settings.VECTOR_WRITE_BATCH_SIZE or 256


def _vector_write_retry_policy() -> tuple[int, float]:
    max_retries = settings.VECTOR_WRITE_MAX_RETRIES or 1
    backoff = float(settings.VECTOR_WRITE_RETRY_BACKOFF_SEC or 0.5)
    return max_retries, backoff


def _log_chunk_vector_retry(
    *,
    tenant_id: UUID,
    document_id: UUID,
    attempt: int,
    max_attempts: int,
    batch_size: int,
    backoff: float,
    error: Exception,
) -> None:
    log_metrics(
        {
            "event": "ingest.vector_write.retry",
            "tenant_id": str(tenant_id),
            "document_id": str(document_id),
            "attempt": attempt,
            "max_retries": max_attempts,
            "batch_size": batch_size,
            "backoff_sec": round(float(backoff), 3),
            "error": str(error)[:200],
        }
    )
    logger.warning(
        "Vector write failed (attempt %s/%s), retrying in %.2fs: %s",
        attempt,
        max_attempts,
        backoff,
        str(error)[:200],
    )


class ChunkVectorWriter:
    """Own vector space resolution, writes, retries, and cleanup for one caller session."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def _load_dataset_metadata(self, *, tenant_id: UUID, dataset_id: UUID | None) -> dict[str, Any]:
        if dataset_id is None:
            return {}
        row = (
            self._db.query(DBDataset.dataset_metadata)
            .filter(
                DBDataset.tenant_id == tenant_id,
                DBDataset.id == dataset_id,
            )
            .first()
        )
        if row is None:
            raise LookupError("dataset not found")
        metadata = row[0]
        if metadata is None:
            return {}
        if not isinstance(metadata, dict):
            raise TypeError("dataset metadata must be an object")
        return dict(metadata)

    def resolve_document_runtime(self, *, tenant_id: UUID, document_id: UUID) -> DatasetEmbeddingRuntimeConfig:
        try:
            row = (
                self._db.query(DBDocument.dataset_id)
                .filter(
                    DBDocument.tenant_id == tenant_id,
                    DBDocument.id == document_id,
                )
                .first()
            )
            if row is None:
                raise dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id)
            return resolve_dataset_embedding_runtime(
                self._load_dataset_metadata(tenant_id=tenant_id, dataset_id=row[0])
            )
        except (DatasetScopedEmbeddingRuntimeResolutionError, ValueError):
            raise
        except Exception as exc:
            raise dataset_scoped_runtime_unavailable(document_id=document_id, tenant_id=tenant_id) from exc

    def _dataset_scoped_vector_collections_for_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
    ) -> list[str]:
        collection_name_column = DocumentChunk.doc_metadata["vector_collection_name"].astext.label(
            "vector_collection_name"
        )
        embedding_space_column = DocumentChunk.doc_metadata["embedding_space_hash"].astext.label("embedding_space_hash")
        rows = self._db.query(collection_name_column, embedding_space_column).filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
        )

        collections: set[str] = set()
        derived_spaces: set[str] = set()
        for raw_collection_name, raw_space_hash in rows.yield_per(_CHUNK_METADATA_SCAN_BATCH_SIZE):
            collection_name = str(raw_collection_name or "").strip()
            if collection_name:
                collections.add(collection_name)
                continue
            space_hash = str(raw_space_hash or "").strip()
            if not space_hash:
                continue
            # Older chunk metadata may be missing the persisted dataset-scoped marker even
            # though vectors were written into the dataset-scoped collection for this
            # embedding space. Full document cleanup always deletes the default store
            # separately, so include the derived dataset-scoped collection here to clear
            # both plausible locations instead of leaving stale vectors behind.
            derived_spaces.add(space_hash)

        for space_hash in derived_spaces:
            collections.add(
                collection_name_for_embedding_space(
                    space_hash=space_hash,
                    dataset_scoped=True,
                )
            )
        return sorted(collections)

    def _delete_dataset_scoped_chunk_vectors(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        metadata_filter: dict[str, Any] | None = None,
    ) -> None:
        if settings.VECTOR_BACKEND.strip().lower() != "milvus":
            return
        try:
            runtime = self.resolve_document_runtime(tenant_id=tenant_id, document_id=document_id)
        except ValueError as exc:
            logger.warning("Skipping dataset-scoped vector cleanup for invalid embedding config: %s", exc)
            return
        collections = self._dataset_scoped_vector_collections_for_document(
            tenant_id=tenant_id,
            document_id=document_id,
        )
        if not collections and not runtime.dataset_scoped:
            return
        for collection_name in collections or [runtime.collection_name]:
            adapter = get_milvus_adapter(resolve_collection_name(collection_name))
            if metadata_filter:
                adapter.delete_by_document_id_and_filter(
                    document_id=document_id,
                    tenant_id=tenant_id,
                    metadata_filter=metadata_filter,
                )
            else:
                adapter.delete_by_document_id(document_id, tenant_id=tenant_id)

    def delete(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        metadata_filter: dict[str, Any],
    ) -> None:
        if milvus_backend_enabled():
            self._delete_dataset_scoped_chunk_vectors(
                tenant_id=tenant_id,
                document_id=document_id,
                metadata_filter=metadata_filter,
            )
        get_vector_store().delete_by_document_id_and_filter(
            document_id=document_id,
            tenant_id=tenant_id,
            metadata_filter=metadata_filter,
        )

    def upsert_document_chunk_vector(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        content: str,
        metadata: dict[str, Any],
    ) -> str | None:
        runtime = self.resolve_document_runtime(
            tenant_id=tenant_id,
            document_id=document_id,
        )
        vector_metadata = dict(metadata or {})
        vector_metadata["embedding_space_hash"] = runtime.embedding_space_hash
        vector_metadata["dataset_scoped"] = bool(runtime.dataset_scoped)
        if runtime.dataset_scoped:
            vector_metadata["vector_collection_name"] = runtime.collection_name
        else:
            vector_metadata.pop("vector_collection_name", None)
        ids = self.upsert(
            [{"content": str(content or ""), "metadata": vector_metadata}],
            document_id=document_id,
            tenant_id=tenant_id,
            enable_vectors=True,
            embedding_runtime=runtime,
        )
        vector_id = ids[0] if ids else None
        if vector_id:
            metadata.clear()
            metadata.update(vector_metadata)
        return str(vector_id) if vector_id else None

    def _document_vector_item(
        self,
        *,
        doc: dict[str, Any],
        document_id: UUID,
        tenant_id: UUID,
        index: int,
    ) -> dict[str, Any]:
        meta = dict(doc.get("metadata") or {})
        chunk_id = meta.get("chunk_id")
        pipeline_hash = str(meta.get("pipeline_hash") or "")[:64]
        doc_pipeline_key = str(
            meta.get("doc_pipeline_key") or (f"{document_id}:{pipeline_hash}" if pipeline_hash else str(document_id))
        )[:256]
        img_id = meta.get("img_id") or meta.get("image_id") or ""
        image_id = meta.get("image_id") or meta.get("img_id") or ""
        image_url = meta.get("image_url") or meta.get("img_url") or ""
        item_id = str(chunk_id) if chunk_id else f"{document_id}_{index}"
        return {
            "id": item_id,
            "content": str(doc.get("content") or ""),
            "metadata": {
                "tenant_id": str(tenant_id),
                "dataset_id": str(meta.get("dataset_id") or ""),
                "embedding_space_hash": str(meta.get("embedding_space_hash") or ""),
                "document_id": str(document_id),
                "chunk_index": int(meta.get("chunk_index", index) or 0),
                "chunk_id": str(chunk_id) if chunk_id else "",
                "pipeline_hash": pipeline_hash,
                "doc_pipeline_key": doc_pipeline_key,
                "page_number": int(meta.get("page") or meta.get("page_number") or 0),
                "source": str(meta.get("source", "unknown"))[:500],
                "file_type": str(meta.get("file_type", "unknown"))[:20],
                "img_id": str(img_id)[:500],
                "image_id": str(image_id)[:500],
                "image_url": str(image_url)[:2000],
            },
        }

    def _write_dataset_scoped_chunk_vectors(
        self,
        docs: list[dict[str, Any]],
        *,
        document_id: UUID,
        tenant_id: UUID,
        runtime: DatasetEmbeddingRuntimeConfig,
    ) -> list[str | None]:
        adapter: Any = None
        ids: list[str | None] = []
        try:
            embeddings = create_embeddings_for_runtime(runtime)
            adapter = get_milvus_adapter(resolve_collection_name(runtime.collection_name))
            max_retries, backoff = _vector_write_retry_policy()
            batch_size = max(1, _vector_write_batch_size())
            for batch_start in range(0, len(docs), batch_size):
                batch_docs = docs[batch_start : batch_start + batch_size]
                items = [
                    self._document_vector_item(
                        doc=doc,
                        document_id=document_id,
                        tenant_id=tenant_id,
                        index=batch_start + index,
                    )
                    for index, doc in enumerate(batch_docs)
                ]
                vectors = embeddings.embed_documents([str(doc.get("content") or "") for doc in batch_docs])
                batch_ids: list[str | None] = []
                attempt_backoff = backoff
                for attempt in range(max_retries + 1):
                    try:
                        batch_ids = adapter.add_vectors(
                            items,
                            embeddings=vectors,
                            batch_size=batch_size,
                            upsert=True,
                        )
                        break
                    except Exception as exc:  # noqa: BLE001
                        if attempt >= max_retries:
                            raise
                        _log_chunk_vector_retry(
                            tenant_id=tenant_id,
                            document_id=document_id,
                            attempt=attempt + 1,
                            max_attempts=max_retries + 1,
                            batch_size=len(items),
                            backoff=attempt_backoff,
                            error=exc,
                        )
                        time.sleep(attempt_backoff)
                        attempt_backoff *= 2
                if len(batch_ids) != len(batch_docs):
                    raise ValueError(f"vector ids length {len(batch_ids)} != docs length {len(batch_docs)}")
                ids.extend(batch_ids)

            return ids
        except Exception as exc:
            logger.warning(
                "Dataset-scoped vector write failed collection=%s space=%s: %s",
                runtime.collection_name,
                runtime.embedding_space_hash,
                str(exc)[:200],
            )
            # Batched writes are not atomic: earlier batches are already committed to the
            # collection when a later batch fails. The caller treats this as a failed write
            # and will retry or mark the document failed, so drop the partial vectors instead
            # of leaving orphans that no chunk row points at.
            self._rollback_partial_dataset_scoped_vectors(
                adapter,
                ids,
                document_id=document_id,
                collection_name=runtime.collection_name,
            )
            raise

    def _rollback_partial_dataset_scoped_vectors(
        self,
        adapter: Any,
        written_ids: list[str | None],
        *,
        document_id: UUID,
        collection_name: str,
    ) -> None:
        stale_ids = [str(vector_id) for vector_id in written_ids if vector_id]
        if adapter is None or not stale_ids:
            return
        try:
            adapter.delete(stale_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to roll back %s partial dataset-scoped vectors document=%s collection=%s: %s",
                len(stale_ids),
                str(document_id),
                collection_name,
                str(exc)[:200],
            )

    def _write_chunk_vector_batch_with_retries(
        self,
        batch: list[dict[str, Any]],
        *,
        document_id: UUID,
        tenant_id: UUID,
        max_retries: int,
        backoff: float,
    ) -> tuple[list[str | None], float]:
        vector_store = get_vector_store()
        for attempt in range(max_retries + 1):
            try:
                ids = list(vector_store.add_documents(batch, document_id, tenant_id))
                dual_write_shadow_vectors_best_effort(batch, document_id=document_id, tenant_id=tenant_id)
                return ids, backoff
            except Exception as exc:  # noqa: BLE001
                if attempt >= max_retries:
                    raise
                _log_chunk_vector_retry(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    attempt=attempt + 1,
                    max_attempts=max_retries + 1,
                    batch_size=len(batch),
                    backoff=backoff,
                    error=exc,
                )
                time.sleep(backoff)
                backoff *= 2
        return [], backoff

    def _write_default_chunk_vectors(
        self,
        docs: list[dict[str, Any]],
        *,
        document_id: UUID,
        tenant_id: UUID,
    ) -> list[str | None]:
        batch_size = _vector_write_batch_size()
        max_retries, backoff = _vector_write_retry_policy()
        out: list[str | None] = []
        for i in range(0, len(docs), batch_size):
            batch = docs[i : i + batch_size]
            ids, backoff = self._write_chunk_vector_batch_with_retries(
                batch,
                document_id=document_id,
                tenant_id=tenant_id,
                max_retries=max_retries,
                backoff=backoff,
            )
            out.extend(ids)
        return out

    def upsert(
        self,
        docs: list[dict[str, Any]],
        *,
        document_id: UUID,
        tenant_id: UUID,
        enable_vectors: bool,
        embedding_runtime: DatasetEmbeddingRuntimeConfig,
    ) -> list[str | None]:
        if not docs:
            return []

        if not enable_vectors:
            return [None] * len(docs)

        runtime = embedding_runtime
        try:
            if runtime.dataset_scoped and milvus_backend_enabled():
                return self._write_dataset_scoped_chunk_vectors(
                    docs,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    runtime=runtime,
                )
            out = self._write_default_chunk_vectors(docs, document_id=document_id, tenant_id=tenant_id)
            if len(out) != len(docs):
                raise ValueError(f"vector ids length {len(out)} != docs length {len(docs)}")
            return out
        except Exception as exc:
            logger.warning("Failed to store vectors: %s", exc)
            try:
                self.cleanup_attempted_chunks(docs, document_id=document_id, tenant_id=tenant_id, runtime=runtime)
            except Exception as cleanup_error:
                logger.warning("Failed to clean attempted chunk vectors after vector write failure: %s", cleanup_error)
            raise

    def delete_default(
        self,
        *,
        document_id: UUID,
        tenant_id: UUID,
        metadata_filter: dict[str, Any] | None = None,
    ) -> None:
        store = get_vector_store()
        if metadata_filter is None:
            store.delete_by_document_id(document_id, tenant_id=tenant_id)
        else:
            store.delete_by_document_id_and_filter(
                document_id=document_id,
                tenant_id=tenant_id,
                metadata_filter=metadata_filter,
            )

    def cleanup_attempted_chunks(
        self,
        docs: list[dict[str, Any]],
        *,
        document_id: UUID,
        tenant_id: UUID,
        runtime: DatasetEmbeddingRuntimeConfig,
    ) -> None:
        if not docs:
            return
        chunk_ids = list({str(doc["metadata"]["chunk_id"]) for doc in docs})
        metadata_filter = {"chunk_id": {"$in": chunk_ids}}
        if runtime.dataset_scoped and milvus_backend_enabled():
            get_milvus_adapter(resolve_collection_name(runtime.collection_name)).delete_by_document_id_and_filter(
                document_id=document_id,
                tenant_id=tenant_id,
                metadata_filter=metadata_filter,
            )
        else:
            self.delete_default(document_id=document_id, tenant_id=tenant_id, metadata_filter=metadata_filter)
