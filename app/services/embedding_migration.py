"""
Embedding blue-green migration helpers (Gap5).

Goal:
- Support zero/low-downtime embedding model swaps by indexing into a shadow Milvus collection
  using a shadow embedding config while the primary collection stays live.

This module is intentionally best-effort:
- It must never break product flows (dual-write is handled elsewhere).
- It avoids storing raw chunk text in Redis progress payloads.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.core.pipeline_versions import get_active_pipeline_hash
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.chunking.contextual_enrichment import build_context_prefix
from app.rag.core.logging import get_logger
from app.rag.embedding import create_langchain_embeddings_from_config
from app.rag.embedding.utils import current_embedding_space_hash, embedding_space_hash_for_config
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

logger = get_logger("embedding_migration")

_redis_client: Any | None = None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _get_redis_client():  # noqa: ANN202
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis  # type: ignore

        _redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_timeout=1,
            socket_connect_timeout=1,
            decode_responses=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding migration progress disabled (redis init failed): %s", str(exc)[:200])
        _redis_client = None
    return _redis_client


def _invalidate_redis_client() -> None:
    global _redis_client
    _redis_client = None


def _progress_key(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    target_collection: str,
    target_space_hash: str,
) -> str:
    prefix = str(getattr(settings, "EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX", "embmig") or "embmig").strip() or "embmig"
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
    shadow_space = embedding_space_hash_for_config(
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
    return create_langchain_embeddings_from_config(
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
    return create_langchain_embeddings_from_config(
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
    doc_ready_clause = or_(
        DBDocument.status == "completed",
        (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true"),  # type: ignore[attr-defined]
    )
    q = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
        .order_by(DBDocument.updated_at.asc().nullslast(), DBDocument.id.asc())
    )
    if dataset_id is not None:
        q = q.filter(DBDocument.dataset_id == dataset_id)
    return q


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
    shadow_collection = str(cfg["collection"])
    shadow_space = str(cfg["embedding_space_hash"])
    primary_collection = str(getattr(settings, "MILVUS_COLLECTION_NAME", "documents") or "documents").strip()
    primary_space = str(current_embedding_space_hash() or "").strip()

    payload: dict[str, Any] = {
        "schema": "mimirq.embedding_blue_green_backfill.v1",
        "ts": _utc_now_iso(),
        "ok": True,
        "execute": bool(execute),
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

    redis = _get_redis_client()
    progress_key = _progress_key(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        target_collection=shadow_collection,
        target_space_hash=shadow_space,
    )

    # Resolve embeddings + adapter once.
    try:
        embeddings = _init_shadow_embeddings()
    except Exception as exc:  # noqa: BLE001
        payload["ok"] = False
        payload["error"] = f"shadow_embeddings_init_failed:{type(exc).__name__}"
        return payload

    try:
        adapter = get_milvus_adapter(resolve_collection_name(shadow_collection))
    except Exception as exc:  # noqa: BLE001
        payload["ok"] = False
        payload["error"] = f"shadow_adapter_init_failed:{type(exc).__name__}"
        return payload

    eff_embed_batch_size = int(embed_batch_size or getattr(settings, "EMBEDDING_API_BATCH_SIZE", 64) or 64)
    eff_embed_batch_size = max(1, min(256, eff_embed_batch_size))

    doc_q = _active_documents_query(db, tenant_id=tenant_id, dataset_id=dataset_id)
    if int(document_limit or 0) > 0:
        doc_q = doc_q.limit(int(document_limit))

    for doc in doc_q.all():
        payload["counters"]["documents_scanned"] += 1

        try:
            doc_id = UUID(str(doc.id))
        except Exception:
            payload["counters"]["errors"] += 1
            continue

        doc_meta = dict(getattr(doc, "doc_metadata", None) or {})
        active_hash = get_active_pipeline_hash(doc_meta) or ""
        doc_title = _derive_document_title_for_prefix(filename=getattr(doc, "filename", None), doc_metadata=doc_meta)

        chunks_q = db.query(DocumentChunk).filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == doc_id,
            DocumentChunk.disabled_at.is_(None),
        )
        if active_hash:
            # Prefer the JSONB key if available; fallback handled below.
            try:
                chunks_q = chunks_q.filter(
                    DocumentChunk.doc_metadata["pipeline_hash"].astext == active_hash  # type: ignore[attr-defined]
                )
            except Exception as exc:
                logger.debug("Ignoring pipeline hash JSONB filter fallback failure: %s", exc)

        chunks_q = chunks_q.order_by(DocumentChunk.chunk_index.asc())
        if int(chunk_limit_per_document or 0) > 0:
            chunks_q = chunks_q.limit(int(chunk_limit_per_document))
        chunks = list(chunks_q.all() or [])

        if not chunks:
            continue

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

            # Ensure doc_pipeline_key is present for later selective deletes.
            if active_hash:
                meta.setdefault("pipeline_hash", active_hash)
                meta.setdefault("doc_pipeline_key", f"{doc_id}:{active_hash}")

            embed_text = _build_shadow_embedding_text(content=content, meta=meta, document_title=doc_title)
            vector_docs.append({"id": chunk_uuid, "content": embed_text, "metadata": meta})
            vector_docs.extend(_field_aware_extras_for_chunk(chunk_uuid=chunk_uuid, meta=meta))

        if not vector_docs:
            continue

        payload["counters"]["documents_indexed"] += 1
        payload["counters"]["chunks_indexed"] += int(len(chunks))

        if not execute:
            payload["counters"]["vectors_skipped"] += int(len(vector_docs))
            _save_progress(
                redis,
                key=progress_key,
                payload={
                    "schema": "mimirq.embedding_migration_progress.v1",
                    "ts": _utc_now_iso(),
                    "execute": False,
                    "scope": {
                        "tenant_id": str(tenant_id),
                        "dataset_id": str(dataset_id) if dataset_id is not None else None,
                        "shadow_collection": shadow_collection,
                        "shadow_embedding_space_hash": shadow_space,
                    },
                    "counters": dict(payload.get("counters") or {}),
                },
            )
            continue

        # Write vectors (bounded batches).
        try:
            for batch in _batched(vector_docs, batch_size=eff_embed_batch_size):
                texts = [str(x.get("content") or "") for x in batch]
                vecs = embeddings.embed_documents(texts)
                adapter.add_vectors(batch, embeddings=vecs, batch_size=int(getattr(settings, "VECTOR_WRITE_BATCH_SIZE", 256) or 256), upsert=True)
                payload["counters"]["vectors_written"] += int(len(batch))
        except Exception as exc:  # noqa: BLE001
            payload["counters"]["errors"] += 1
            logger.warning(
                "Shadow backfill write failed doc=%s err=%s",
                str(doc_id),
                str(exc)[:200],
            )

        _save_progress(
            redis,
            key=progress_key,
            payload={
                "schema": "mimirq.embedding_migration_progress.v1",
                "ts": _utc_now_iso(),
                "execute": True,
                "scope": {
                    "tenant_id": str(tenant_id),
                    "dataset_id": str(dataset_id) if dataset_id is not None else None,
                    "shadow_collection": shadow_collection,
                    "shadow_embedding_space_hash": shadow_space,
                },
                "counters": dict(payload.get("counters") or {}),
            },
        )

    payload["elapsed_sec"] = round(max(0.0, float(time.perf_counter() - t0)), 3)
    return payload


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

    shadow_collection = str(cfg["collection"])
    shadow_space = str(cfg["embedding_space_hash"])
    primary_collection = str(getattr(settings, "MILVUS_COLLECTION_NAME", "documents") or "documents").strip()
    primary_space = str(current_embedding_space_hash() or "").strip()

    cap = max(1, min(500, int(sample_n or 0)))
    k = max(1, min(50, int(top_k or 0)))

    doc_ready_clause = or_(
        DBDocument.status == "completed",
        (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true"),  # type: ignore[attr-defined]
    )

    doc_active_hash = func.coalesce(
        DBDocument.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
        DBDocument.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        "",
    )
    chunk_hash = func.coalesce(
        DocumentChunk.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
        "",
    )

    chunks_q = (
        db.query(DocumentChunk.id, DocumentChunk.content)
        .join(
            DBDocument,
            and_(
                DBDocument.id == DocumentChunk.document_id,
                DBDocument.tenant_id == DocumentChunk.tenant_id,
            ),
        )
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
        )
        .filter(doc_ready_clause)
        .filter(DocumentChunk.disabled_at.is_(None))
        .filter(chunk_hash == doc_active_hash)
        .order_by(DocumentChunk.updated_at.desc().nullslast(), DocumentChunk.id.asc())
        .limit(cap)
    )
    if dataset_id is not None:
        chunks_q = chunks_q.filter(DBDocument.dataset_id == dataset_id)

    rows = list(chunks_q.all() or [])
    queries: list[tuple[str, str]] = []
    for cid, content in rows:
        q = str(content or "").strip()
        if not q:
            continue
        if int(max_query_chars or 0) > 0 and len(q) > int(max_query_chars or 0):
            q = q[: int(max_query_chars or 0)]
        queries.append((str(cid), q))

    payload: dict[str, Any] = {
        "schema": "mimirq.embedding_migration_overlap.v1",
        "ts": _utc_now_iso(),
        "ok": True,
        "scope": {"tenant_id": str(tenant_id), "dataset_id": str(dataset_id) if dataset_id is not None else None},
        "primary": {"collection": primary_collection, "embedding_space_hash": primary_space},
        "shadow": {"collection": shadow_collection, "embedding_space_hash": shadow_space},
        "sampled_queries": int(len(queries)),
        "top_k": int(k),
        "elapsed_sec": None,
    }

    if not queries:
        payload["ok"] = False
        payload["error"] = "no_queries"
        return payload

    try:
        cur_emb = _init_current_embeddings()
        sh_emb = _init_shadow_embeddings()
    except Exception as exc:  # noqa: BLE001
        payload["ok"] = False
        payload["error"] = f"embeddings_init_failed:{type(exc).__name__}"
        payload["elapsed_sec"] = round(max(0.0, float(time.perf_counter() - t0)), 3)
        return payload

    try:
        primary_adapter = get_milvus_adapter(resolve_collection_name(primary_collection))
        shadow_adapter = get_milvus_adapter(resolve_collection_name(shadow_collection))
    except Exception as exc:  # noqa: BLE001
        payload["ok"] = False
        payload["error"] = f"milvus_adapter_init_failed:{type(exc).__name__}"
        payload["elapsed_sec"] = round(max(0.0, float(time.perf_counter() - t0)), 3)
        return payload

    expr = _milvus_scope_expr(tenant_id=tenant_id, dataset_id=dataset_id)

    overlaps: list[float] = []
    self_hit_primary = 0
    self_hit_shadow = 0
    errors = 0
    for chunk_id, q in queries:
        try:
            qv_primary = cur_emb.embed_query(q)
            qv_shadow = sh_emb.embed_query(q)
            a = primary_adapter.search(query_vector=qv_primary, top_k=k, expr=expr)
            b = shadow_adapter.search(query_vector=qv_shadow, top_k=k, expr=expr)
            ids_a = [str(r.get("id") or "") for r in a if str(r.get("id") or "").strip()]
            ids_b = [str(r.get("id") or "") for r in b if str(r.get("id") or "").strip()]
            overlaps.append(_overlap_ratio(ids_a, ids_b, k=k))
            if chunk_id in ids_a:
                self_hit_primary += 1
            if chunk_id in ids_b:
                self_hit_shadow += 1
        except Exception:
            errors += 1
            continue

    payload["errors"] = int(errors)
    if overlaps:
        overlaps_sorted = sorted(float(x) for x in overlaps)
        avg = sum(overlaps_sorted) / float(len(overlaps_sorted))
        payload["overlap"] = {
            "avg": float(avg),
            "min": float(overlaps_sorted[0]),
            "p50": float(overlaps_sorted[len(overlaps_sorted) // 2]),
            "max": float(overlaps_sorted[-1]),
        }
    else:
        payload["overlap"] = None
    payload["self_hit"] = {
        "primary_ratio": float(self_hit_primary / max(1, len(queries))),
        "shadow_ratio": float(self_hit_shadow / max(1, len(queries))),
    }
    payload["elapsed_sec"] = round(max(0.0, float(time.perf_counter() - t0)), 3)
    return payload


__all__ = [
    "load_embedding_migration_progress",
    "resolve_shadow_embedding_config",
    "run_embedding_migration_overlap_check",
    "run_shadow_collection_backfill",
]
