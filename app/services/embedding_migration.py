"""
Embedding blue-green migration helpers (Gap5).

Goal:
- Support zero/low-downtime embedding model swaps by indexing into a shadow Milvus collection
  using a shadow embedding config while the primary collection stays live.

This module is intentionally best-effort:
- It must never break product flows (dual-write is handled elsewhere).
- It avoids storing raw chunk text in Redis progress payloads.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.core.pipeline_versions import get_active_pipeline_hash
from app.core.redis_client import LazyRedisClient
from app.rag.core.logging import get_logger

logger = get_logger("embedding_migration")

_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": False,
    },
    on_error=lambda exc: logger.warning(
        "Embedding migration progress disabled (redis init failed): %s",
        str(exc)[:200],
    ),
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_embeddings_from_config(**kwargs: Any) -> Any:
    from app.rag.embedding import create_langchain_embeddings_from_config

    return create_langchain_embeddings_from_config(**kwargs)


def _embedding_space_hash_for_shadow_config(*, provider: str, model: str, base_url: str, length: int) -> str:
    from app.rag.embedding.utils import embedding_space_hash_for_config

    return embedding_space_hash_for_config(
        provider=provider,
        model=model,
        base_url=base_url,
        length=length,
    )


def _current_space_hash() -> str:
    from app.rag.embedding.utils import current_embedding_space_hash

    return str(current_embedding_space_hash() or "").strip()


def _get_collection_adapter(collection_name: str) -> Any:
    from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

    return get_milvus_adapter(resolve_collection_name(collection_name))


def _document_model() -> Any:
    from app.models.document import Document as DocumentModel

    return DocumentModel


def _document_chunk_model() -> Any:
    from app.models.document import DocumentChunk as DocumentChunkModel

    return DocumentChunkModel


@dataclass
class _BackfillRuntime:
    payload: dict[str, Any]
    shadow_collection: str
    shadow_space: str
    redis: Any
    progress_key: str
    embeddings: Any | None
    adapter: Any | None
    embed_batch_size: int


@dataclass
class _OverlapRuntime:
    payload: dict[str, Any]
    shadow_collection: str
    shadow_space: str
    primary_collection: str
    top_k: int


def _progress_key(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    target_collection: str,
    target_space_hash: str,
) -> str:
    prefix = (
        str(getattr(settings, "EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX", "embmig") or "embmig").strip() or "embmig"
    )
    scope = str(dataset_id) if dataset_id is not None else "all"
    return f"{prefix}:{tenant_id}:{scope}:{target_collection}:{target_space_hash}"


def _save_progress(redis, *, key: str, payload: dict[str, Any]) -> None:  # noqa: ANN001
    if redis is None:
        return
    ttl = int(getattr(settings, "EMBEDDING_MIGRATION_PROGRESS_TTL_SEC", 7 * 24 * 3600) or 0)
    try:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if ttl > 0:
            redis.set(key, raw, ex=ttl)
        else:
            redis.set(key, raw)
    except Exception:
        _invalidate_redis_client()


def load_embedding_migration_progress(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    target_collection: str,
    target_space_hash: str,
) -> dict[str, Any] | None:
    """Load best-effort migration progress from Redis (PII-safe)."""
    redis = _get_redis_client()
    if redis is None:
        return None
    key = _progress_key(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        target_collection=target_collection,
        target_space_hash=target_space_hash,
    )
    try:
        raw = redis.get(key)
    except Exception:
        _invalidate_redis_client()
        return None
    if not raw:
        return None
    try:
        decoded = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        payload = json.loads(decoded)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def resolve_shadow_embedding_config() -> dict[str, str] | None:
    """
    Resolve the shadow embedding config from Settings.

    Returns a small dict safe to log/return (no API keys).
    """
    if not bool(getattr(settings, "EMBEDDING_SHADOW_ENABLED", False)):
        return None

    shadow_collection = str(getattr(settings, "MILVUS_SHADOW_COLLECTION_NAME", "") or "").strip()
    shadow_model = str(getattr(settings, "EMBEDDING_SHADOW_MODEL", "") or "").strip()
    if not shadow_collection or not shadow_model:
        return None

    provider_raw = (
        str(getattr(settings, "EMBEDDING_SHADOW_PROVIDER", "") or "").strip().lower()
        or str(getattr(settings, "EMBEDDING_PROVIDER", "openai_compatible") or "openai_compatible").strip().lower()
    )
    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider_raw, "openai_compatible")

    base_url = (
        str(getattr(settings, "EMBEDDING_SHADOW_API_BASE", "") or "").strip()
        or str(getattr(settings, "EMBEDDING_API_BASE", "") or "").strip()
        or str(getattr(settings, "LLM_API_BASE", "") or "").strip()
    )
    shadow_space = _embedding_space_hash_for_shadow_config(
        provider=mapped_provider,
        model=shadow_model,
        base_url=base_url,
        length=16,
    )

    return {
        "provider": mapped_provider,
        "model": shadow_model,
        "base_url": base_url,
        "collection": shadow_collection,
        "embedding_space_hash": shadow_space,
    }


def _init_shadow_embeddings():  # noqa: ANN202
    cfg = resolve_shadow_embedding_config()
    if cfg is None:
        raise RuntimeError("shadow embedding config not enabled")

    api_key = (
        str(getattr(settings, "EMBEDDING_SHADOW_API_KEY", "") or "").strip()
        or str(getattr(settings, "EMBEDDING_API_KEY", "") or "").strip()
        or str(getattr(settings, "LLM_API_KEY", "") or "").strip()
    )
    return _create_embeddings_from_config(
        provider=str(cfg["provider"]),
        model=str(cfg["model"]),
        api_key=api_key,
        base_url=str(cfg["base_url"] or ""),
        dimension=None,  # Auto-detect
    )


def _init_current_embeddings():  # noqa: ANN202
    provider_raw = (settings.EMBEDDING_PROVIDER or "local").lower()
    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider_raw, "openai_compatible")
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE
    return _create_embeddings_from_config(
        provider=mapped_provider,
        model=str(settings.EMBEDDING_MODEL or "text-embedding-3-small"),
        api_key=api_key or "",
        base_url=base_url or "",
        dimension=None,  # Auto-detect
    )


def _batched(values: list[Any], *, batch_size: int) -> Iterable[list[Any]]:
    n = max(1, int(batch_size or 0))
    for i in range(0, len(values), n):
        yield values[i : i + n]


def _build_shadow_embedding_text(
    *,
    content: str,
    meta: dict[str, Any],
    document_title: str | None,
) -> str:
    """
    Build the embedding text for a chunk, aligning with ingestion behavior.

    Notes:
    - Contextual retrieval prefixes are deterministic (no LLM).
    - "Section" structural prefix is applied when embedding_context_prefix_enabled=true.
    """
    raw_body = str(content or "")
    embed_text = raw_body

    # Avoid prefixing non-text assets (images/tables).
    from app.rag.chunking.contextual_enrichment import build_context_prefix
    from app.services.indexer import _build_embedding_text, _should_prefix_embedding  # noqa: WPS433

    contextual_enabled = bool(meta.get("embedding_contextual_retrieval_enabled"))
    if contextual_enabled and raw_body and _should_prefix_embedding(meta):
        try:
            prefix = build_context_prefix(
                raw_body,
                document_title=document_title,
                meta=meta,
                max_prefix_chars=int(getattr(settings, "CONTEXTUAL_RETRIEVAL_PREFIX_MAX_CHARS", 240) or 240),
                keywords_top_k=int(getattr(settings, "CONTEXTUAL_RETRIEVAL_KEYWORDS_TOP_K", 6) or 6),
                keywords_max_chars=int(getattr(settings, "CONTEXTUAL_RETRIEVAL_KEYWORDS_MAX_CHARS", 2000) or 2000),
            )
            if prefix:
                embed_text = prefix + "\n" + raw_body
        except Exception as exc:
            logger.debug("Ignoring contextual embedding prefix build failure: %s", exc)

    if bool(meta.get("embedding_context_prefix_enabled")):
        embed_text = _build_embedding_text(embed_text, meta)

    return embed_text


def _derive_document_title_for_prefix(*, filename: Any, doc_metadata: Any) -> str | None:
    from app.services.indexer import _derive_document_title  # noqa: WPS433

    try:
        return _derive_document_title(filename, doc_metadata, max_chars=120)
    except Exception:
        return None


def _field_aware_extras_for_chunk(
    *,
    chunk_uuid: str,
    meta: dict[str, Any],
) -> list[dict[str, Any]]:
    if not bool(meta.get("embedding_field_aware_enabled")):
        return []

    from app.services.indexer import (  # noqa: WPS433
        _extract_heading_for_embedding,
        _extract_title_for_embedding,
        _should_prefix_embedding,
    )

    if not _should_prefix_embedding(meta):
        return []

    out: list[dict[str, Any]] = []
    title = _extract_title_for_embedding(meta)
    if title:
        meta_t = dict(meta)
        meta_t["chunk_id"] = f"{chunk_uuid}:title"
        out.append({"id": meta_t["chunk_id"], "content": f"[Title] {title}", "metadata": meta_t})

    heading = _extract_heading_for_embedding(meta)
    if heading:
        meta_h = dict(meta)
        meta_h["chunk_id"] = f"{chunk_uuid}:heading"
        out.append({"id": meta_h["chunk_id"], "content": f"[Heading] {heading}", "metadata": meta_h})

    return out


def _active_documents_query(db: Session, *, tenant_id: UUID, dataset_id: UUID | None):  # noqa: ANN202
    document_model = _document_model()
    doc_ready_clause = or_(
        document_model.status == "completed",
        (document_model.doc_metadata["active_pipeline_ready"].astext == "true"),  # type: ignore[attr-defined]
    )
    q = (
        db.query(document_model)
        .filter(
            document_model.tenant_id == tenant_id,
            document_model.archived_at.is_(None),
            document_model.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
        .order_by(document_model.updated_at.asc().nullslast(), document_model.id.asc())
    )
    if dataset_id is not None:
        q = q.filter(document_model.dataset_id == dataset_id)
    return q


def _build_progress_scope(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    shadow_collection: str,
    shadow_space: str,
) -> dict[str, Any]:
    return {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id) if dataset_id is not None else None,
        "shadow_collection": shadow_collection,
        "shadow_embedding_space_hash": shadow_space,
    }


def _build_backfill_payload(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    cfg: dict[str, str],
) -> tuple[dict[str, Any], str, str]:
    shadow_collection = str(cfg["collection"])
    shadow_space = str(cfg["embedding_space_hash"])
    primary_collection = str(getattr(settings, "MILVUS_COLLECTION_NAME", "documents") or "documents").strip()
    primary_space = _current_space_hash()
    payload: dict[str, Any] = {
        "schema": "mimirq.embedding_blue_green_backfill.v1",
        "ts": _utc_now_iso(),
        "ok": True,
        "execute": False,
        "scope": {
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id) if dataset_id is not None else None,
        },
        "primary": {
            "collection": primary_collection,
            "embedding_space_hash": primary_space,
        },
        "shadow": {
            "collection": shadow_collection,
            "embedding_space_hash": shadow_space,
            "provider": cfg.get("provider"),
            "model": cfg.get("model"),
            "base_url": cfg.get("base_url"),
        },
        "counters": {
            "documents_scanned": 0,
            "documents_indexed": 0,
            "chunks_indexed": 0,
            "vectors_written": 0,
            "vectors_skipped": 0,
            "errors": 0,
        },
        "elapsed_sec": None,
    }
    return payload, shadow_collection, shadow_space


def _build_progress_payload(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    shadow_collection: str,
    shadow_space: str,
    execute: bool,
    counters: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "mimirq.embedding_migration_progress.v1",
        "ts": _utc_now_iso(),
        "execute": bool(execute),
        "scope": _build_progress_scope(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            shadow_collection=shadow_collection,
            shadow_space=shadow_space,
        ),
        "counters": dict(counters or {}),
    }


def _build_backfill_runtime(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    cfg: dict[str, str],
    execute: bool,
    embed_batch_size: int | None,
) -> _BackfillRuntime:
    payload, shadow_collection, shadow_space = _build_backfill_payload(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        cfg=cfg,
    )
    payload["execute"] = bool(execute)
    redis = _get_redis_client()
    progress_key = _progress_key(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        target_collection=shadow_collection,
        target_space_hash=shadow_space,
    )
    effective_batch_size = int(embed_batch_size or getattr(settings, "EMBEDDING_API_BATCH_SIZE", 64) or 64)
    effective_batch_size = max(1, min(256, effective_batch_size))
    return _BackfillRuntime(
        payload=payload,
        shadow_collection=shadow_collection,
        shadow_space=shadow_space,
        redis=redis,
        progress_key=progress_key,
        embeddings=None,
        adapter=None,
        embed_batch_size=effective_batch_size,
    )


def _load_document_chunks(
    *,
    db: Session,
    tenant_id: UUID,
    doc_id: UUID,
    active_hash: str,
    chunk_limit_per_document: int,
) -> list[Any]:
    document_chunk_model = _document_chunk_model()
    chunks_q = db.query(document_chunk_model).filter(
        document_chunk_model.tenant_id == tenant_id,
        document_chunk_model.document_id == doc_id,
        document_chunk_model.disabled_at.is_(None),
    )
    if active_hash:
        try:
            chunks_q = chunks_q.filter(
                document_chunk_model.doc_metadata["pipeline_hash"].astext == active_hash  # type: ignore[attr-defined]
            )
        except Exception as exc:
            logger.debug("Ignoring pipeline hash JSONB filter fallback failure: %s", exc)
    chunks_q = chunks_q.order_by(document_chunk_model.chunk_index.asc())
    if int(chunk_limit_per_document or 0) > 0:
        chunks_q = chunks_q.limit(int(chunk_limit_per_document))
    return list(chunks_q.all() or [])


def _build_vector_docs_for_document(
    *,
    doc: Any,
    chunks: list[Any],
    tenant_id: UUID,
    doc_id: UUID,
    active_hash: str,
    shadow_space: str,
    doc_title: str | None,
) -> list[dict[str, Any]]:
    vector_docs: list[dict[str, Any]] = []
    for chunk in chunks:
        chunk_uuid = str(getattr(chunk, "id", "") or "").strip()
        if not chunk_uuid:
            continue
        content = str(getattr(chunk, "content", "") or "")
        if not content.strip():
            continue

        meta0 = getattr(chunk, "doc_metadata", None)
        meta = dict(meta0 or {}) if isinstance(meta0, dict) else {}
        meta.setdefault("tenant_id", str(tenant_id))
        meta.setdefault("dataset_id", str(getattr(doc, "dataset_id", "") or "") or "")
        meta.setdefault("document_id", str(doc_id))
        meta.setdefault("chunk_index", int(getattr(chunk, "chunk_index", 0) or 0))
        meta["chunk_id"] = chunk_uuid
        meta["embedding_space_hash"] = shadow_space
        if active_hash:
            meta.setdefault("pipeline_hash", active_hash)
            meta.setdefault("doc_pipeline_key", f"{doc_id}:{active_hash}")

        embed_text = _build_shadow_embedding_text(
            content=content,
            meta=meta,
            document_title=doc_title,
        )
        vector_docs.append({"id": chunk_uuid, "content": embed_text, "metadata": meta})
        vector_docs.extend(_field_aware_extras_for_chunk(chunk_uuid=chunk_uuid, meta=meta))
    return vector_docs


def _persist_backfill_progress(
    *,
    runtime: _BackfillRuntime,
    tenant_id: UUID,
    dataset_id: UUID | None,
    execute: bool,
) -> None:
    _save_progress(
        runtime.redis,
        key=runtime.progress_key,
        payload=_build_progress_payload(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            shadow_collection=runtime.shadow_collection,
            shadow_space=runtime.shadow_space,
            execute=execute,
            counters=dict(runtime.payload.get("counters") or {}),
        ),
    )


def _write_vector_docs(runtime: _BackfillRuntime, *, vector_docs: list[dict[str, Any]]) -> int:
    written = 0
    write_batch_size = int(getattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256) or 256)
    for batch in _batched(vector_docs, batch_size=runtime.embed_batch_size):
        texts = [str(item.get("content") or "") for item in batch]
        embeddings = runtime.embeddings.embed_documents(texts)
        runtime.adapter.add_vectors(
            batch,
            embeddings=embeddings,
            batch_size=write_batch_size,
            upsert=True,
        )
        written += int(len(batch))
    return written


def _process_backfill_document(
    *,
    runtime: _BackfillRuntime,
    db: Session,
    doc: Any,
    tenant_id: UUID,
    dataset_id: UUID | None,
    chunk_limit_per_document: int,
    execute: bool,
) -> None:
    runtime.payload["counters"]["documents_scanned"] += 1
    try:
        doc_id = UUID(str(doc.id))
    except Exception:
        runtime.payload["counters"]["errors"] += 1
        return

    doc_meta = dict(getattr(doc, "doc_metadata", None) or {})
    active_hash = get_active_pipeline_hash(doc_meta) or ""
    doc_title = _derive_document_title_for_prefix(
        filename=getattr(doc, "filename", None),
        doc_metadata=doc_meta,
    )
    chunks = _load_document_chunks(
        db=db,
        tenant_id=tenant_id,
        doc_id=doc_id,
        active_hash=active_hash,
        chunk_limit_per_document=chunk_limit_per_document,
    )
    if not chunks:
        return

    vector_docs = _build_vector_docs_for_document(
        doc=doc,
        chunks=chunks,
        tenant_id=tenant_id,
        doc_id=doc_id,
        active_hash=active_hash,
        shadow_space=runtime.shadow_space,
        doc_title=doc_title,
    )
    if not vector_docs:
        return

    runtime.payload["counters"]["documents_indexed"] += 1
    runtime.payload["counters"]["chunks_indexed"] += int(len(chunks))
    if not execute:
        runtime.payload["counters"]["vectors_skipped"] += int(len(vector_docs))
        _persist_backfill_progress(
            runtime=runtime,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            execute=False,
        )
        return

    try:
        runtime.payload["counters"]["vectors_written"] += _write_vector_docs(
            runtime,
            vector_docs=vector_docs,
        )
    except Exception as exc:  # noqa: BLE001
        runtime.payload["counters"]["errors"] += 1
        logger.warning("Shadow backfill write failed doc=%s err=%s", str(doc_id), str(exc)[:200])
    _persist_backfill_progress(
        runtime=runtime,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        execute=True,
    )


def run_shadow_collection_backfill(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID | None = None,
    document_limit: int = 0,
    chunk_limit_per_document: int = 0,
    embed_batch_size: int | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """
    Backfill active document chunk vectors into the shadow collection.

    This is typically run while the system still uses the primary embedding config
    for queries (blue phase).
    """
    cfg = resolve_shadow_embedding_config()
    if cfg is None:
        return {"ok": False, "error": "shadow_config_disabled"}

    t0 = time.perf_counter()
    try:
        runtime = _build_backfill_runtime(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            cfg=cfg,
            execute=execute,
            embed_batch_size=embed_batch_size,
        )
        runtime.embeddings = _init_shadow_embeddings()
    except Exception as exc:  # noqa: BLE001
        payload, _, _ = _build_backfill_payload(tenant_id=tenant_id, dataset_id=dataset_id, cfg=cfg)
        payload["ok"] = False
        payload["error"] = f"shadow_embeddings_init_failed:{type(exc).__name__}"
        return payload

    try:
        runtime.adapter = _get_collection_adapter(runtime.shadow_collection)
    except Exception as exc:  # noqa: BLE001
        payload = dict(runtime.payload)
        payload["ok"] = False
        payload["error"] = f"shadow_adapter_init_failed:{type(exc).__name__}"
        return payload

    doc_q = _active_documents_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
    if int(document_limit or 0) > 0:
        doc_q = doc_q.limit(int(document_limit))

    for doc in doc_q.all():
        _process_backfill_document(
            runtime=runtime,
            db=db,
            doc=doc,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            chunk_limit_per_document=chunk_limit_per_document,
            execute=execute,
        )

    runtime.payload["elapsed_sec"] = round(max(0.0, float(time.perf_counter() - t0)), 3)
    return runtime.payload


def _milvus_scope_expr(*, tenant_id: UUID, dataset_id: UUID | None) -> str:
    parts = [f'tenant_id == "{str(tenant_id)}"']
    if dataset_id is not None:
        parts.append(f'dataset_id == "{str(dataset_id)}"')
    return " and ".join(parts)


def _overlap_ratio(a: list[str], b: list[str], *, k: int) -> float:
    if k <= 0:
        return 0.0
    sa = set(a[:k])
    sb = set(b[:k])
    if not sa and not sb:
        return 1.0
    return float(len(sa & sb) / float(k))


def _build_overlap_payload(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    shadow_collection: str,
    shadow_space: str,
    primary_collection: str,
    primary_space: str,
    top_k: int,
) -> dict[str, Any]:
    return {
        "schema": "mimirq.embedding_migration_overlap.v1",
        "ts": _utc_now_iso(),
        "ok": True,
        "scope": {
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id) if dataset_id is not None else None,
        },
        "primary": {
            "collection": primary_collection,
            "embedding_space_hash": primary_space,
        },
        "shadow": {
            "collection": shadow_collection,
            "embedding_space_hash": shadow_space,
        },
        "sampled_queries": 0,
        "top_k": int(top_k),
        "elapsed_sec": None,
    }


def _build_overlap_runtime(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    cfg: dict[str, str],
    top_k: int,
) -> _OverlapRuntime:
    shadow_collection = str(cfg["collection"])
    shadow_space = str(cfg["embedding_space_hash"])
    primary_collection = str(getattr(settings, "MILVUS_COLLECTION_NAME", "documents") or "documents").strip()
    primary_space = _current_space_hash()
    payload = _build_overlap_payload(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        shadow_collection=shadow_collection,
        shadow_space=shadow_space,
        primary_collection=primary_collection,
        primary_space=primary_space,
        top_k=top_k,
    )
    return _OverlapRuntime(
        payload=payload,
        shadow_collection=shadow_collection,
        shadow_space=shadow_space,
        primary_collection=primary_collection,
        top_k=top_k,
    )


def _load_overlap_queries(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID | None,
    sample_n: int,
    max_query_chars: int,
) -> list[tuple[str, str]]:
    document_model = _document_model()
    document_chunk_model = _document_chunk_model()
    cap = max(1, min(500, int(sample_n or 0)))
    doc_ready_clause = or_(
        document_model.status == "completed",
        (document_model.doc_metadata["active_pipeline_ready"].astext == "true"),  # type: ignore[attr-defined]
    )
    doc_active_hash = func.coalesce(
        document_model.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
        document_model.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        "",
    )
    chunk_hash = func.coalesce(
        document_chunk_model.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        "",
    )
    chunks_q = (
        db.query(document_chunk_model.id, document_chunk_model.content)
        .join(
            document_model,
            and_(
                document_model.id == document_chunk_model.document_id,
                document_model.tenant_id == document_chunk_model.tenant_id,
            ),
        )
        .filter(
            document_model.tenant_id == tenant_id,
            document_model.archived_at.is_(None),
            document_model.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
        .filter(document_chunk_model.disabled_at.is_(None))
        .filter(chunk_hash == doc_active_hash)
        .order_by(document_chunk_model.updated_at.desc().nullslast(), document_chunk_model.id.asc())
        .limit(cap)
    )
    if dataset_id is not None:
        chunks_q = chunks_q.filter(document_model.dataset_id == dataset_id)

    queries: list[tuple[str, str]] = []
    query_char_cap = int(max_query_chars or 0)
    for chunk_id, content in list(chunks_q.all() or []):
        query = str(content or "").strip()
        if not query:
            continue
        if query_char_cap > 0 and len(query) > query_char_cap:
            query = query[:query_char_cap]
        queries.append((str(chunk_id), query))
    return queries


def _init_overlap_embeddings() -> tuple[Any, Any]:
    return _init_current_embeddings(), _init_shadow_embeddings()


def _init_overlap_adapters(runtime: _OverlapRuntime) -> tuple[Any, Any]:
    return (
        _get_collection_adapter(runtime.primary_collection),
        _get_collection_adapter(runtime.shadow_collection),
    )


def _result_ids(results: list[dict[str, Any]]) -> list[str]:
    return [str(result.get("id") or "") for result in results if str(result.get("id") or "").strip()]


def _build_overlap_summary(
    *,
    overlaps: list[float],
    self_hit_primary: int,
    self_hit_shadow: int,
    query_count: int,
    errors: int,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "errors": int(errors),
        "self_hit": {
            "primary_ratio": float(self_hit_primary / max(1, query_count)),
            "shadow_ratio": float(self_hit_shadow / max(1, query_count)),
        },
    }
    if overlaps:
        overlaps_sorted = sorted(float(value) for value in overlaps)
        avg = sum(overlaps_sorted) / float(len(overlaps_sorted))
        summary["overlap"] = {
            "avg": float(avg),
            "min": float(overlaps_sorted[0]),
            "p50": float(overlaps_sorted[len(overlaps_sorted) // 2]),
            "max": float(overlaps_sorted[-1]),
        }
    else:
        summary["overlap"] = None
    return summary


def _measure_overlap(
    *,
    queries: list[tuple[str, str]],
    top_k: int,
    expr: str,
    current_embeddings: Any,
    shadow_embeddings: Any,
    primary_adapter: Any,
    shadow_adapter: Any,
) -> dict[str, Any]:
    overlaps: list[float] = []
    self_hit_primary = 0
    self_hit_shadow = 0
    errors = 0
    for chunk_id, query in queries:
        try:
            primary_vector = current_embeddings.embed_query(query)
            shadow_vector = shadow_embeddings.embed_query(query)
            primary_results = primary_adapter.search(query_vector=primary_vector, top_k=top_k, expr=expr)
            shadow_results = shadow_adapter.search(query_vector=shadow_vector, top_k=top_k, expr=expr)
            primary_ids = _result_ids(primary_results)
            shadow_ids = _result_ids(shadow_results)
            overlaps.append(_overlap_ratio(primary_ids, shadow_ids, k=top_k))
            if chunk_id in primary_ids:
                self_hit_primary += 1
            if chunk_id in shadow_ids:
                self_hit_shadow += 1
        except Exception:
            errors += 1
    return _build_overlap_summary(
        overlaps=overlaps,
        self_hit_primary=self_hit_primary,
        self_hit_shadow=self_hit_shadow,
        query_count=len(queries),
        errors=errors,
    )


def run_embedding_migration_overlap_check(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID | None = None,
    sample_n: int = 50,
    top_k: int = 10,
    max_query_chars: int = 800,
) -> dict[str, Any]:
    """
    Best-effort overlap check between primary and shadow collections.

    This uses chunk contents as queries (PII-sensitive) but only returns aggregate stats.
    """
    cfg = resolve_shadow_embedding_config()
    if cfg is None:
        return {"ok": False, "error": "shadow_config_disabled"}

    t0 = time.perf_counter()
    k = max(1, min(50, int(top_k or 0)))
    runtime = _build_overlap_runtime(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        cfg=cfg,
        top_k=k,
    )
    queries = _load_overlap_queries(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        sample_n=sample_n,
        max_query_chars=max_query_chars,
    )
    runtime.payload["sampled_queries"] = int(len(queries))
    if not queries:
        runtime.payload["ok"] = False
        runtime.payload["error"] = "no_queries"
        return runtime.payload

    try:
        current_embeddings, shadow_embeddings = _init_overlap_embeddings()
    except Exception as exc:  # noqa: BLE001
        runtime.payload["ok"] = False
        runtime.payload["error"] = f"embeddings_init_failed:{type(exc).__name__}"
        runtime.payload["elapsed_sec"] = round(max(0.0, float(time.perf_counter() - t0)), 3)
        return runtime.payload

    try:
        primary_adapter, shadow_adapter = _init_overlap_adapters(runtime)
    except Exception as exc:  # noqa: BLE001
        runtime.payload["ok"] = False
        runtime.payload["error"] = f"milvus_adapter_init_failed:{type(exc).__name__}"
        runtime.payload["elapsed_sec"] = round(max(0.0, float(time.perf_counter() - t0)), 3)
        return runtime.payload

    expr = _milvus_scope_expr(tenant_id=tenant_id, dataset_id=dataset_id)
    runtime.payload.update(
        _measure_overlap(
            queries=queries,
            top_k=k,
            expr=expr,
            current_embeddings=current_embeddings,
            shadow_embeddings=shadow_embeddings,
            primary_adapter=primary_adapter,
            shadow_adapter=shadow_adapter,
        )
    )
    runtime.payload["elapsed_sec"] = round(max(0.0, float(time.perf_counter() - t0)), 3)
    return runtime.payload


__all__ = [
    "load_embedding_migration_progress",
    "resolve_shadow_embedding_config",
    "run_embedding_migration_overlap_check",
    "run_shadow_collection_backfill",
]
