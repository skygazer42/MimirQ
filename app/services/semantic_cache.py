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


import hashlib
import json
import time
from typing import Any

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.core.redis_client import LazyRedisClient
from app.rag.core.hashing import stable_hash, stable_json_dumps
from app.rag.core.logging import get_logger
from app.rag.embedding.utils import current_embedding_space_hash
from app.storage.vector.milvus import MilvusMaintenanceError, get_milvus_adapter, resolve_collection_name

logger = get_logger("semantic_cache")
_LOOKUP_CLEANUP_MAX_DELETE = 4
_RETENTION_MAX_SCAN_DEFAULT = 1000

_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": False,
    },
    on_error=lambda exc: logger.warning(
        "Semantic cache disabled (redis init failed): %s",
        str(exc)[:200],
    ),
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate
_embeddings: Any | None = None
_adapter: Any | None = None


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
    behavior_hash: str | None = None,
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
        "behavior_hash": str(behavior_hash or "") or None,
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


def _coerce_epoch(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _flush_lookup_cleanup(
    *,
    adapter: Any,
    cleanup_ids: list[str],
    meta: dict[str, Any],
) -> None:
    meta["cleanup_attempted"] = len(cleanup_ids)
    if not cleanup_ids:
        return
    try:
        adapter.delete(cleanup_ids)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Ignoring semantic cache lookup cleanup failure: %s", exc)


def get_cached_semantic_payload(
    *,
    tenant_id: str,
    account_id: str,
    dataset_id: str | None,
    corpus_cache_token: str,
    behavior_hash: str | None = None,
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
            behavior_hash=behavior_hash,
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
        adapter = _get_adapter()
        results = adapter.search(vec, top_k=search_k, metadata_filter={"tenant_id": str(tenant_id)})
        meta["search_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    except Exception as exc:  # noqa: BLE001
        meta["skip_reason"] = "search_error"
        meta["error"] = str(exc)[:200]
        return None, meta

    pipeline_key = str(current_embedding_space_hash() or "") or ""
    now_epoch = int(time.time())
    cleanup_budget = max(0, int(_LOOKUP_CLEANUP_MAX_DELETE))
    cleanup_ids: list[str] = []
    cleanup_seen: set[str] = set()
    meta["cleanup_budget"] = cleanup_budget
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
        expires_at = _coerce_epoch(md.get("expires_at_epoch"))
        if expires_at is not None and expires_at <= now_epoch:
            meta["expired_vectors_skipped"] = int(meta.get("expired_vectors_skipped", 0) or 0) + 1
            if len(cleanup_ids) < cleanup_budget and rid not in cleanup_seen:
                cleanup_seen.add(rid)
                cleanup_ids.append(rid)
            continue
        key = _redis_payload_key(tenant_id=str(tenant_id), vector_id=rid)
        try:
            raw = client.get(key)
        except Exception as exc:  # noqa: BLE001
            _flush_lookup_cleanup(adapter=adapter, cleanup_ids=cleanup_ids, meta=meta)
            meta["skip_reason"] = "redis_read_error"
            meta["error"] = str(exc)[:200]
            _invalidate_redis_client()
            return None, meta
        if not raw:
            meta["orphan_vectors_skipped"] = int(meta.get("orphan_vectors_skipped", 0) or 0) + 1
            if len(cleanup_ids) < cleanup_budget and rid not in cleanup_seen:
                cleanup_seen.add(rid)
                cleanup_ids.append(rid)
            continue

        try:
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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
        _flush_lookup_cleanup(adapter=adapter, cleanup_ids=cleanup_ids, meta=meta)
        return out, meta

    _flush_lookup_cleanup(adapter=adapter, cleanup_ids=cleanup_ids, meta=meta)
    return None, meta


def set_cached_semantic_payload(
    *,
    tenant_id: str,
    account_id: str,
    dataset_id: str | None,
    corpus_cache_token: str,
    behavior_hash: str | None = None,
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
            behavior_hash=behavior_hash,
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


def run_semantic_cache_retention(
    *,
    tenant_id: str | Any | None = None,
    dry_run: bool,
    max_delete: int,
    max_scan: int | None = None,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    now_epoch_i = int(now_epoch or time.time())
    try:
        max_delete_i = max(1, int(max_delete or 0))
    except Exception:
        max_delete_i = 1000
    try:
        max_scan_i = max(1, int(max_scan or _RETENTION_MAX_SCAN_DEFAULT))
    except Exception:
        max_scan_i = _RETENTION_MAX_SCAN_DEFAULT

    tenant_id_s = None if tenant_id is None else str(tenant_id)
    summary: dict[str, Any] = {
        "job": "semantic-cache",
        "tenant_id": tenant_id_s,
        "dry_run": bool(dry_run),
        "max_delete": int(max_delete_i),
        "max_scan": int(max_scan_i),
        "ran_at_epoch": int(now_epoch_i),
        "scanned": 0,
        "exhausted": False,
        "scan_limit_reached": False,
        "eligible": 0,
        "deleted": 0,
        "expired_candidates": 0,
        "legacy_rows_seen": 0,
        "legacy_orphan_candidates": 0,
        "legacy_rows_preserved": 0,
        "legacy_rows_skipped": 0,
        "failed": False,
        "errors": [],
    }

    try:
        adapter = _get_adapter()
    except Exception as exc:  # noqa: BLE001
        summary["failed"] = True
        summary["errors"].append(str(exc)[:200])
        return summary

    client = _get_redis_client()
    delete_ids: list[str] = []
    exhausted = False
    page_size = max(1, min(max_delete_i, 250))
    iterator = None

    try:
        iterator = adapter.open_semantic_cache_maintenance_iterator(
            tenant_id=str(tenant_id_s or ""),
            batch_size=min(page_size, max_scan_i),
        )
        while (not exhausted) and summary["scanned"] < max_scan_i and len(delete_ids) < max_delete_i:
            rows = iterator.next_batch()
            if not rows:
                exhausted = True
                break

            remaining_scan = max_scan_i - int(summary["scanned"] or 0)
            batch_rows = rows[:remaining_scan]
            summary["scanned"] += len(batch_rows)
            if len(rows) > len(batch_rows):
                exhausted = False

            for row in batch_rows:
                if len(delete_ids) >= max_delete_i:
                    break
                if not isinstance(row, dict):
                    continue
                rid = str(row.get("id") or "").strip()
                row_tenant_id = str(row.get("tenant_id") or "").strip()
                if not rid or not row_tenant_id:
                    summary["failed"] = True
                    summary["errors"].append("semantic cache maintenance row missing tenant scope")
                    break

                expires_at = _coerce_epoch(row.get("expires_at_epoch"))
                if expires_at is not None:
                    if expires_at <= now_epoch_i:
                        summary["expired_candidates"] += 1
                        delete_ids.append(rid)
                    continue

                summary["legacy_rows_seen"] += 1
                if client is None:
                    summary["legacy_rows_skipped"] += 1
                    continue

                key = _redis_payload_key(tenant_id=row_tenant_id, vector_id=rid)
                try:
                    raw = client.get(key)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Ignoring semantic cache retention redis check failure: %s", exc)
                    client = None
                    summary["legacy_rows_skipped"] += 1
                    continue
                if raw:
                    summary["legacy_rows_preserved"] += 1
                    continue
                summary["legacy_orphan_candidates"] += 1
                delete_ids.append(rid)

            if summary["failed"]:
                break
    except MilvusMaintenanceError as exc:
        summary["failed"] = True
        summary["errors"].append(str(exc)[:200])
    except Exception as exc:  # noqa: BLE001
        summary["failed"] = True
        summary["errors"].append(str(exc)[:200])
    finally:
        if iterator is not None:
            try:
                iterator.close()
            except MilvusMaintenanceError as exc:
                summary["failed"] = True
                summary["errors"].append(str(exc)[:200])

    summary["exhausted"] = bool(exhausted)
    summary["scan_limit_reached"] = bool((not exhausted) and summary["scanned"] >= max_scan_i and len(delete_ids) < max_delete_i)
    summary["eligible"] = len(delete_ids)
    if (not dry_run) and delete_ids and (not summary["failed"]):
        try:
            adapter.delete(delete_ids)
            summary["deleted"] = len(delete_ids)
        except Exception as exc:  # noqa: BLE001
            summary["failed"] = True
            summary["errors"].append(str(exc)[:200])

    return summary


__all__ = [
    "build_semantic_cache_scope_hash",
    "get_cached_semantic_payload",
    "run_semantic_cache_retention",
    "set_cached_semantic_payload",
]
