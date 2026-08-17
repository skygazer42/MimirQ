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
    name = (
        str(getattr(settings, "SEMANTIC_CACHE_COLLECTION_NAME", "semantic_cache") or "semantic_cache").strip()
        or "semantic_cache"
    )
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


def _semantic_cache_lookup_precheck(
    *,
    tenant_id: str,
    account_id: str,
    dataset_id: str | None,
    corpus_cache_token: str,
    document_ids: list[str],
) -> tuple[dict[str, Any], int]:
    meta: dict[str, Any] = {"enabled": bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", False)), "hit": False}
    if not meta["enabled"]:
        meta["skip_reason"] = "disabled"
        return meta, 0

    ttl = int(getattr(settings, "SEMANTIC_CACHE_TTL_SEC", 300) or 0)
    if ttl <= 0:
        meta["skip_reason"] = "ttl_zero"
        return meta, ttl
    if not tenant_id or not str(tenant_id).strip():
        meta["skip_reason"] = "missing_tenant"
        return meta, ttl
    if not account_id or not str(account_id).strip():
        meta["skip_reason"] = "missing_account"
        return meta, ttl
    if (not document_ids) and not (dataset_id or "").strip():
        meta["skip_reason"] = "missing_scope"
        return meta, ttl
    if not corpus_cache_token or not str(corpus_cache_token).strip():
        meta["skip_reason"] = "missing_corpus_cache_token"
        return meta, ttl
    return meta, ttl


def _semantic_cache_scope_hash_or_skip(meta: dict[str, Any], **kwargs: Any) -> str | None:
    try:
        scope_hash, _vector_id = build_semantic_cache_scope_hash(**kwargs)
        return scope_hash
    except Exception:
        meta["skip_reason"] = "signature_error"
        return None


def _semantic_cache_embedding_or_skip(meta: dict[str, Any], *, query: str) -> list[float] | None:
    try:
        started_at = time.perf_counter()
        vector = _get_embeddings().embed_query(query or "")
        meta["embed_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
        return vector
    except Exception:
        meta["skip_reason"] = "embed_error"
        return None


def _semantic_cache_search_results_or_skip(
    meta: dict[str, Any], *, tenant_id: str, vector: list[float], top_k: int
) -> tuple[Any, list[dict[str, Any]]] | None:
    try:
        started_at = time.perf_counter()
        adapter = _get_adapter()
        results = adapter.search(vector, top_k=top_k, metadata_filter={"tenant_id": str(tenant_id)})
        meta["search_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
        return adapter, results
    except Exception as exc:  # noqa: BLE001
        meta["skip_reason"] = "search_error"
        meta["error"] = str(exc)[:200]
        return None


def _maybe_queue_semantic_cache_cleanup(
    *,
    cleanup_ids: list[str],
    cleanup_seen: set[str],
    cleanup_budget: int,
    vector_id: str,
) -> None:
    if len(cleanup_ids) >= cleanup_budget or vector_id in cleanup_seen:
        return
    cleanup_seen.add(vector_id)
    cleanup_ids.append(vector_id)


def _semantic_cache_result_matches(
    result: dict[str, Any],
    *,
    tenant_id: str,
    account_id: str,
    scope_hash: str,
    corpus_cache_token: str,
    embedding_space_hash: str,
) -> tuple[str, float, dict[str, Any]] | None:
    try:
        score = float(result.get("score") or 0.0)
    except Exception:
        score = 0.0
    metadata = result.get("metadata") or {}
    vector_id = str(result.get("id") or "").strip()
    if not vector_id:
        return None
    checks = (
        str(metadata.get("tenant_id") or "") == str(tenant_id),
        str(metadata.get("account_id") or "") == str(account_id or ""),
        str(metadata.get("scope_hash") or "") == str(scope_hash),
        str(metadata.get("corpus_cache_token") or "") == str(corpus_cache_token),
        str(metadata.get("embedding_space_hash") or "") == embedding_space_hash,
    )
    if not all(checks):
        return None
    return vector_id, score, metadata


def _semantic_cache_payload_list(raw: Any) -> list[dict[str, Any]] | None:
    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001
        get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
        return None
    if not isinstance(payload, list):
        return None
    return [item for item in payload if isinstance(item, dict)]


def _cached_semantic_payload_from_results(
    *,
    results: list[dict[str, Any]],
    meta: dict[str, Any],
    adapter: Any,
    client: Any,
    tenant_id: str,
    account_id: str,
    scope_hash: str,
    corpus_cache_token: str,
    threshold: float,
    embedding_space_hash: str,
    now_epoch: int,
    cleanup_budget: int,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    cleanup_ids: list[str] = []
    cleanup_seen: set[str] = set()
    meta["cleanup_budget"] = cleanup_budget
    for result in results or []:
        match = _semantic_cache_result_matches(
            result,
            tenant_id=tenant_id,
            account_id=account_id,
            scope_hash=scope_hash,
            corpus_cache_token=corpus_cache_token,
            embedding_space_hash=embedding_space_hash,
        )
        if match is None:
            continue
        vector_id, score, metadata = match
        if score < threshold:
            continue
        expires_at = _coerce_epoch(metadata.get("expires_at_epoch"))
        if expires_at is not None and expires_at <= now_epoch:
            meta["expired_vectors_skipped"] = int(meta.get("expired_vectors_skipped", 0) or 0) + 1
            _maybe_queue_semantic_cache_cleanup(
                cleanup_ids=cleanup_ids,
                cleanup_seen=cleanup_seen,
                cleanup_budget=cleanup_budget,
                vector_id=vector_id,
            )
            continue
        key = _redis_payload_key(tenant_id=str(tenant_id), vector_id=vector_id)
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
            _maybe_queue_semantic_cache_cleanup(
                cleanup_ids=cleanup_ids,
                cleanup_seen=cleanup_seen,
                cleanup_budget=cleanup_budget,
                vector_id=vector_id,
            )
            continue

        payload = _semantic_cache_payload_list(raw)
        if payload is None:
            continue

        meta["hit"] = True
        meta["score"] = float(score)
        meta["vector_id"] = vector_id
        _flush_lookup_cleanup(adapter=adapter, cleanup_ids=cleanup_ids, meta=meta)
        return payload, meta

    _flush_lookup_cleanup(adapter=adapter, cleanup_ids=cleanup_ids, meta=meta)
    return None, meta


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
    meta, ttl = _semantic_cache_lookup_precheck(
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        corpus_cache_token=corpus_cache_token,
        document_ids=document_ids,
    )
    if meta.get("skip_reason"):
        return None, meta

    threshold = float(getattr(settings, "SEMANTIC_CACHE_SCORE_THRESHOLD", 0.95) or 0.95)
    search_k = int(getattr(settings, "SEMANTIC_CACHE_SEARCH_TOP_K", 5) or 5)
    search_k = max(1, min(20, search_k))

    scope_hash = _semantic_cache_scope_hash_or_skip(
        meta,
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
    if scope_hash is None:
        return None, meta

    client = _get_redis_client()
    if client is None:
        meta["skip_reason"] = "redis_unavailable"
        return None, meta

    vector = _semantic_cache_embedding_or_skip(meta, query=query)
    if vector is None:
        return None, meta
    search_result = _semantic_cache_search_results_or_skip(meta, tenant_id=tenant_id, vector=vector, top_k=search_k)
    if search_result is None:
        return None, meta
    adapter, results = search_result

    return _cached_semantic_payload_from_results(
        results=results,
        meta=meta,
        adapter=adapter,
        client=client,
        tenant_id=tenant_id,
        account_id=account_id,
        scope_hash=scope_hash,
        corpus_cache_token=corpus_cache_token,
        threshold=threshold,
        embedding_space_hash=str(current_embedding_space_hash() or "") or "",
        now_epoch=int(time.time()),
        cleanup_budget=max(0, int(_LOOKUP_CLEANUP_MAX_DELETE)),
    )


def _semantic_cache_store_precheck() -> tuple[int, Any | None]:
    if not bool(getattr(settings, "SEMANTIC_CACHE_ENABLED", False)):
        return 0, None
    ttl = int(getattr(settings, "SEMANTIC_CACHE_TTL_SEC", 300) or 0)
    if ttl <= 0:
        return ttl, None
    return ttl, _get_redis_client()


def _semantic_cache_store_key_and_scope(**kwargs: Any) -> tuple[str, str] | None:
    try:
        return build_semantic_cache_scope_hash(**kwargs)
    except Exception:
        return None


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
    ttl, client = _semantic_cache_store_precheck()
    if client is None:
        return False

    scope_result = _semantic_cache_store_key_and_scope(
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
    if scope_result is None:
        return False
    scope_hash, vector_id = scope_result

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


def _semantic_cache_retention_limits(
    *, max_delete: int, max_scan: int | None, now_epoch: int | None
) -> tuple[int, int, int]:
    now_epoch_i = int(now_epoch or time.time())
    try:
        max_delete_i = max(1, int(max_delete or 0))
    except Exception:
        max_delete_i = 1000
    try:
        max_scan_i = max(1, int(max_scan or _RETENTION_MAX_SCAN_DEFAULT))
    except Exception:
        max_scan_i = _RETENTION_MAX_SCAN_DEFAULT
    return now_epoch_i, max_delete_i, max_scan_i


def _semantic_cache_retention_summary(
    *, tenant_id: str | None, dry_run: bool, max_delete: int, max_scan: int, now_epoch: int
) -> dict[str, Any]:
    return {
        "job": "semantic-cache",
        "tenant_id": tenant_id,
        "dry_run": bool(dry_run),
        "max_delete": int(max_delete),
        "max_scan": int(max_scan),
        "ran_at_epoch": int(now_epoch),
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


def _evaluate_retention_row(
    *,
    row: Any,
    now_epoch: int,
    client: Any,
    delete_ids: list[str],
    max_delete: int,
    summary: dict[str, Any],
) -> None:
    if len(delete_ids) >= max_delete or not isinstance(row, dict):
        return
    row_id = str(row.get("id") or "").strip()
    row_tenant_id = str(row.get("tenant_id") or "").strip()
    if not row_id or not row_tenant_id:
        summary["failed"] = True
        summary["errors"].append("semantic cache maintenance row missing tenant scope")
        return

    expires_at = _coerce_epoch(row.get("expires_at_epoch"))
    if expires_at is not None:
        if expires_at <= now_epoch:
            summary["expired_candidates"] += 1
            delete_ids.append(row_id)
        return

    summary["legacy_rows_seen"] += 1
    if client is None:
        summary["legacy_rows_skipped"] += 1
        return

    key = _redis_payload_key(tenant_id=row_tenant_id, vector_id=row_id)
    try:
        raw = client.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Ignoring semantic cache retention redis check failure: %s", exc)
        summary["legacy_rows_skipped"] += 1
        return
    if raw:
        summary["legacy_rows_preserved"] += 1
        return
    summary["legacy_orphan_candidates"] += 1
    delete_ids.append(row_id)


def _collect_retention_delete_ids(
    *,
    adapter: Any,
    client: Any,
    tenant_id: str | None,
    now_epoch: int,
    max_delete: int,
    max_scan: int,
    summary: dict[str, Any],
) -> tuple[list[str], bool]:
    delete_ids: list[str] = []
    exhausted = False
    page_size = max(1, min(max_delete, 250))
    iterator = None
    try:
        iterator = adapter.open_semantic_cache_maintenance_iterator(
            tenant_id=str(tenant_id or ""),
            batch_size=min(page_size, max_scan),
        )
        while (not exhausted) and summary["scanned"] < max_scan and len(delete_ids) < max_delete:
            rows = iterator.next_batch()
            if not rows:
                exhausted = True
                break

            remaining_scan = max_scan - int(summary["scanned"] or 0)
            batch_rows = rows[:remaining_scan]
            summary["scanned"] += len(batch_rows)
            if len(rows) > len(batch_rows):
                exhausted = False

            for row in batch_rows:
                _evaluate_retention_row(
                    row=row,
                    now_epoch=now_epoch,
                    client=client,
                    delete_ids=delete_ids,
                    max_delete=max_delete,
                    summary=summary,
                )
            if summary["failed"]:
                break
    finally:
        if iterator is not None:
            try:
                iterator.close()
            except MilvusMaintenanceError as exc:
                summary["failed"] = True
                summary["errors"].append(str(exc)[:200])
    return delete_ids, exhausted


def run_semantic_cache_retention(
    *,
    tenant_id: str | Any | None = None,
    dry_run: bool,
    max_delete: int,
    max_scan: int | None = None,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    now_epoch_i, max_delete_i, max_scan_i = _semantic_cache_retention_limits(
        max_delete=max_delete,
        max_scan=max_scan,
        now_epoch=now_epoch,
    )
    tenant_id_s = None if tenant_id is None else str(tenant_id)
    summary = _semantic_cache_retention_summary(
        tenant_id=tenant_id_s,
        dry_run=dry_run,
        max_delete=max_delete_i,
        max_scan=max_scan_i,
        now_epoch=now_epoch_i,
    )

    try:
        adapter = _get_adapter()
    except Exception as exc:  # noqa: BLE001
        summary["failed"] = True
        summary["errors"].append(str(exc)[:200])
        return summary

    delete_ids: list[str] = []
    exhausted = False
    try:
        delete_ids, exhausted = _collect_retention_delete_ids(
            adapter=adapter,
            client=_get_redis_client(),
            tenant_id=tenant_id_s,
            now_epoch=now_epoch_i,
            max_delete=max_delete_i,
            max_scan=max_scan_i,
            summary=summary,
        )
    except MilvusMaintenanceError as exc:
        summary["failed"] = True
        summary["errors"].append(str(exc)[:200])
    except Exception as exc:  # noqa: BLE001
        summary["failed"] = True
        summary["errors"].append(str(exc)[:200])

    summary["exhausted"] = bool(exhausted)
    summary["scan_limit_reached"] = bool(
        (not exhausted) and summary["scanned"] >= max_scan_i and len(delete_ids) < max_delete_i
    )
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
