"""
Semantic cache (Milvus ANN + Redis payload, best-effort).

Goal:
- Reduce repeated retrieval work for semantically similar queries by storing retrieval outputs
  in a small query-vector index (Milvus collection) with payloads stored in Redis.

Security posture:
- Disabled by default.
- Strict scope binding to (tenant, account, dataset/doc scope, corpus_cache_token, retrieval params).
- Does not store raw query text in Redis keys or Milvus metadata fields.
- Best-effort fail-open: cache failures never break retrieval.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.rag.core.hashing import stable_hash, stable_json_dumps
from app.rag.core.logging import get_logger
from app.rag.embedding.utils import current_embedding_space_hash
from app.storage.vector.milvus import get_milvus_adapter, resolve_collection_name

logger = get_logger("semantic_cache")

_redis_client: Any | None = None
_embeddings: Any | None = None
_adapter: Any | None = None


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
        logger.warning("Semantic cache disabled (redis init failed): %s", str(exc)[:200])
        _redis_client = None
    return _redis_client


def _invalidate_redis_client() -> None:
    global _redis_client
    _redis_client = None


def _get_embeddings():  # noqa: ANN202
    global _embeddings
    if _embeddings is not None:
        return _embeddings
    from app.rag.embedding import create_langchain_embeddings_from_config

    provider = (settings.EMBEDDING_PROVIDER or "local").lower()
    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider, "openai_compatible")
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE
    _embeddings = create_langchain_embeddings_from_config(
        provider=mapped_provider,
        model=settings.EMBEDDING_MODEL,
        api_key=api_key or "",
        base_url=base_url or "",
        dimension=None,  # Auto-detect
    )
    return _embeddings


def _get_adapter():  # noqa: ANN202
    global _adapter
    if _adapter is not None:
        return _adapter
    name = str(getattr(settings, "SEMANTIC_CACHE_COLLECTION_NAME", "semantic_cache") or "semantic_cache").strip() or "semantic_cache"
    _adapter = get_milvus_adapter(resolve_collection_name(name))
    return _adapter


def _hash_doc_scope(document_ids: list[str]) -> str:
    joined = ",".join(sorted(str(d) for d in document_ids if d))
    return hashlib.sha256(joined.encode("utf-8", "ignore")).hexdigest()


def _coerce_metadata_filter(metadata_filter: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata_filter or not isinstance(metadata_filter, dict):
        return None
    # Keep only small JSON-ish objects to avoid huge signatures.
    if len(metadata_filter) > 50:
        return None
    return metadata_filter


def build_semantic_cache_scope_hash(
    *,
    tenant_id: str,
    account_id: str,
    dataset_id: str | None,
    corpus_cache_token: str,
    query: str,
    top_k: int,
    score_threshold: float,
    retrieval_mode: str,
    metadata_filter: dict[str, Any] | None,
    document_ids: list[str],
) -> tuple[str, str]:
    """
    Return (scope_hash, vector_id) for a request.

    Notes:
    - scope_hash excludes the raw query text and is used to keep the semantic cache strictly scoped.
    - vector_id is deterministic (scope_hash + query_hash) to allow idempotent upserts.
    """
    pipeline_key = str(current_embedding_space_hash() or "") or None

    signature: dict[str, Any] = {
        "v": 1,
        "tenant_id": str(tenant_id),
        "account_id": str(account_id or ""),
        "dataset_id": str(dataset_id or "") or None,
        "pipeline_key": str(pipeline_key or "") or None,
        "corpus_cache_token": str(corpus_cache_token or ""),
        "doc_scope": _hash_doc_scope(document_ids),
        "doc_count": int(len([d for d in document_ids if d])),
        "top_k": int(top_k or 0),
        "score_threshold": float(score_threshold or 0.0),
        "retrieval_mode": str(retrieval_mode or "hybrid").strip().lower() or "hybrid",
        "metadata_filter": _coerce_metadata_filter(metadata_filter),
    }

    scope_hash = stable_hash(stable_json_dumps(signature), length=32)
    q_norm = (query or "").strip()
    q_hash = stable_hash(q_norm, length=32)
    vector_id = stable_hash(f"{scope_hash}:{q_hash}", length=32)
    return scope_hash, vector_id


def _redis_payload_key(*, tenant_id: str, vector_id: str) -> str:
    prefix = str(getattr(settings, "SEMANTIC_CACHE_REDIS_PREFIX", "semc") or "semc").strip() or "semc"
    return f"{prefix}:{tenant_id}:{vector_id}"


def get_cached_semantic_payload(
    *,
    tenant_id: str,
    account_id: str,
    dataset_id: str | None,
    corpus_cache_token: str,
    query: str,
    top_k: int,
    score_threshold: float,
    retrieval_mode: str,
    metadata_filter: dict[str, Any] | None,
    document_ids: list[str],
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """
    Lookup semantic cache for a request.

    Returns: (payload_or_none, meta)
    """
    meta: dict[str, Any] = {"enabled": bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", False)), "hit": False}
    if not meta["enabled"]:
        meta["skip_reason"] = "disabled"
        return None, meta

    ttl = int(getattr(settings, "SEMANTIC_CACHE_TTL_SEC", 300) or 0)
    if ttl <= 0:
        meta["skip_reason"] = "ttl_zero"
        return None, meta

    if not tenant_id or not str(tenant_id).strip():
        meta["skip_reason"] = "missing_tenant"
        return None, meta
    if not account_id or not str(account_id).strip():
        meta["skip_reason"] = "missing_account"
        return None, meta
    if (not document_ids) and not (dataset_id or "").strip():
        meta["skip_reason"] = "missing_scope"
        return None, meta
    if not corpus_cache_token or not str(corpus_cache_token).strip():
        meta["skip_reason"] = "missing_corpus_cache_token"
        return None, meta

    threshold = float(getattr(settings, "SEMANTIC_CACHE_SCORE_THRESHOLD", 0.95) or 0.95)
    search_k = int(getattr(settings, "SEMANTIC_CACHE_SEARCH_TOP_K", 5) or 5)
    search_k = max(1, min(20, search_k))

    try:
        scope_hash, _vector_id = build_semantic_cache_scope_hash(
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            corpus_cache_token=corpus_cache_token,
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            retrieval_mode=retrieval_mode,
            metadata_filter=metadata_filter,
            document_ids=document_ids,
        )
    except Exception:
        meta["skip_reason"] = "signature_error"
        return None, meta

    client = _get_redis_client()
    if client is None:
        meta["skip_reason"] = "redis_unavailable"
        return None, meta

    try:
        t0 = time.perf_counter()
        vec = _get_embeddings().embed_query(query or "")
        vec_ms = (time.perf_counter() - t0) * 1000
        meta["embed_ms"] = round(vec_ms, 2)
    except Exception:
        meta["skip_reason"] = "embed_error"
        return None, meta

    try:
        t0 = time.perf_counter()
        # Server-side pushdown is best-effort; we always re-check scope client-side.
        results = _get_adapter().search(vec, top_k=search_k, metadata_filter={"tenant_id": str(tenant_id)})
        meta["search_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    except Exception as exc:  # noqa: BLE001
        meta["skip_reason"] = "search_error"
        meta["error"] = str(exc)[:200]
        return None, meta

    pipeline_key = str(current_embedding_space_hash() or "") or ""
    for r in results or []:
        try:
            score = float(r.get("score") or 0.0)
        except Exception:
            score = 0.0
        if score < threshold:
            continue
        md = r.get("metadata") or {}
        if str(md.get("tenant_id") or "") != str(tenant_id):
            continue
        if str(md.get("account_id") or "") != str(account_id or ""):
            continue
        if str(md.get("scope_hash") or "") != str(scope_hash):
            continue
        if str(md.get("corpus_cache_token") or "") != str(corpus_cache_token):
            continue
        if str(md.get("embedding_space_hash") or "") != pipeline_key:
            continue

        rid = str(r.get("id") or "").strip()
        if not rid:
            continue
        key = _redis_payload_key(tenant_id=str(tenant_id), vector_id=rid)
        try:
            raw = client.get(key)
        except Exception as exc:  # noqa: BLE001
            meta["skip_reason"] = "redis_read_error"
            meta["error"] = str(exc)[:200]
            _invalidate_redis_client()
            return None, meta
        if not raw:
            # Best-effort cleanup: drop orphaned vector pointer.
            try:
                _get_adapter().delete([rid])
            except Exception as exc:
                logger.debug("Ignoring semantic cache orphan vector cleanup failure: %s", exc)
            continue

        try:
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if not isinstance(payload, list):
            continue
        out: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                out.append(item)

        meta["hit"] = True
        meta["score"] = float(score)
        meta["vector_id"] = rid
        return out, meta

    return None, meta


def set_cached_semantic_payload(
    *,
    tenant_id: str,
    account_id: str,
    dataset_id: str | None,
    corpus_cache_token: str,
    query: str,
    top_k: int,
    score_threshold: float,
    retrieval_mode: str,
    metadata_filter: dict[str, Any] | None,
    document_ids: list[str],
    payload: list[dict[str, Any]],
) -> bool:
    if not bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", False)):
        return False

    ttl = int(getattr(settings, "SEMANTIC_CACHE_TTL_SEC", 300) or 0)
    if ttl <= 0:
        return False

    client = _get_redis_client()
    if client is None:
        return False

    try:
        scope_hash, vector_id = build_semantic_cache_scope_hash(
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            corpus_cache_token=corpus_cache_token,
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
            retrieval_mode=retrieval_mode,
            metadata_filter=metadata_filter,
            document_ids=document_ids,
        )
    except Exception:
        return False

    max_bytes = int(getattr(settings, "SEMANTIC_CACHE_MAX_VALUE_BYTES", 400_000) or 0)
    try:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    except Exception:  # noqa: BLE001
        return False
    if max_bytes > 0 and len(raw) > max_bytes:
        return False

    key = _redis_payload_key(tenant_id=str(tenant_id), vector_id=vector_id)
    try:
        if ttl > 0:
            client.set(key, raw, ex=ttl)
        else:
            client.set(key, raw)
    except Exception:  # noqa: BLE001
        _invalidate_redis_client()
        return False

    try:
        vec = _get_embeddings().embed_query(query or "")
    except Exception:
        return False

    now = int(time.time())
    expires_at = now + int(ttl)
    pipeline_key = str(current_embedding_space_hash() or "") or ""
    meta = {
        "tenant_id": str(tenant_id),
        "account_id": str(account_id or ""),
        "dataset_id": str(dataset_id or "") or "",
        "embedding_space_hash": pipeline_key,
        "corpus_cache_token": str(corpus_cache_token),
        "scope_hash": str(scope_hash),
        "created_at_epoch": int(now),
        "expires_at_epoch": int(expires_at),
    }
    try:
        _get_adapter().add_vectors(
            items=[{"id": vector_id, "content": "[semantic_cache]", "metadata": meta}],
            embeddings=[vec],
            upsert=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Semantic cache vector upsert failed: %s", str(exc)[:200])
        return False


__all__ = [
    "build_semantic_cache_scope_hash",
    "get_cached_semantic_payload",
    "set_cached_semantic_payload",
]
