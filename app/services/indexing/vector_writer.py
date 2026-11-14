"""Owned vector writer operations for indexing."""

import logging
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.rag.embedding import create_langchain_embeddings_from_config
from app.rag.embedding.utils import embedding_space_hash_for_config
from app.services.metrics_logger import log_metrics
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

logger = logging.getLogger("indexer")

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
        shadow_space = _shadow_embedding_space_hash(provider=mapped_provider, model=shadow_model, base_url=base_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shadow embedding-space hash failed; dual-write disabled: %s", type(exc).__name__)
        return _cache_shadow_vector_writer(sig, None)

    try:
        emb = create_langchain_embeddings_from_config(
            provider=mapped_provider,
            model=shadow_model,
            api_key=api_key,
            base_url=base_url,
            dimension=None,  # Auto-detect
            cache_space_hash=shadow_space,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shadow embeddings init failed; dual-write disabled: %s", str(exc)[:200])
        return _cache_shadow_vector_writer(sig, None)

    try:
        adapter = get_milvus_adapter(resolve_collection_name(shadow_collection))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shadow Milvus adapter init failed; dual-write disabled: %s", str(exc)[:200])
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
        chunk_id = meta.get("chunk_id")
        if chunk_id is not None:
            chunk_id = str(chunk_id).strip()
        if not chunk_id:
            continue
        content = doc["content"]
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
