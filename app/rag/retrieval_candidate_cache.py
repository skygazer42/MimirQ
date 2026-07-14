"""
Retrieval candidate cache (Redis, short TTL, best-effort).

Goal:
- Reduce repeated vector/BM25/lexical work for identical retrieval requests
  over a short time window (e.g., chat retries, UI refreshes).

Security posture:
- Disabled by default
- Cache key binds to (tenant, account, scope, pipeline) and request signature
- Best-effort fail-open: cache errors never break retrieval
"""


import hashlib
import json
from typing import Any

from app.core.config import settings
from app.core.redis_client import LazyRedisClient
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger

logger = get_logger("rag.candidate_cache")

_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": False,
    },
    on_error=lambda exc: logger.warning(
        "Retrieval candidate cache disabled (redis init failed): %s",
        str(exc)[:200],
    ),
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate


def _hash_doc_scope(document_ids: list[str]) -> str:
    joined = ",".join(sorted(str(d) for d in document_ids if d))
    return hashlib.sha256(joined.encode("utf-8", "ignore")).hexdigest()


def build_retrieval_candidate_cache_key(
    *,
    tenant_id: str,
    account_id: str,
    dataset_id: str | None,
    pipeline_key: str | None,
    corpus_cache_token: str | None = None,
    query: str,
    top_k: int,
    score_threshold: float,
    retrieval_mode: str,
    metadata_filter: dict[str, Any] | None,
    document_ids: list[str],
) -> str:
    """
    Build a short, stable Redis key for a retrieval request.

    Note: We hash the full signature to avoid leaking query text or other potentially
    sensitive information in Redis key names.
    """
    prefix = str(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_PREFIX", "rcand") or "rcand").strip() or "rcand"

    signature: dict[str, Any] = {
        "v": 1,
        "tenant_id": str(tenant_id),
        "account_id": str(account_id or ""),
        "dataset_id": str(dataset_id or "") or None,
        "pipeline_key": str(pipeline_key or "") or None,
        "corpus_cache_token": str(corpus_cache_token or "") or None,
        "doc_scope": _hash_doc_scope(document_ids),
        "doc_count": int(len([d for d in document_ids if d])),
        "query": (query or "").strip(),
        "top_k": int(top_k or 0),
        "score_threshold": float(score_threshold or 0.0),
        "retrieval_mode": str(retrieval_mode or "hybrid").strip().lower() or "hybrid",
        "metadata_filter": metadata_filter if isinstance(metadata_filter, dict) else None,
    }

    raw = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = stable_hash(raw, length=32)
    return f"{prefix}:{tenant_id}:{digest}"


def get_cached_retrieval_candidates(key: str) -> list[dict[str, Any]] | None:
    if not bool(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)):
        return None

    client = _get_redis_client()
    if client is None:
        return None

    try:
        raw = client.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retrieval candidate cache read failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return None

    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None

    if not isinstance(payload, list):
        return None
    out: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            out.append(item)
    return out


def set_cached_retrieval_candidates(key: str, payload: list[dict[str, Any]]) -> bool:
    if not bool(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", False)):
        return False

    client = _get_redis_client()
    if client is None:
        return False

    ttl = int(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 30) or 0)
    max_bytes = int(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES", 400_000) or 0)

    try:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    except Exception:  # noqa: BLE001
        return False

    if max_bytes > 0 and len(raw) > max_bytes:
        return False

    try:
        if ttl > 0:
            client.set(key, raw, ex=ttl)
        else:
            client.set(key, raw)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retrieval candidate cache write failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return False


__all__ = [
    "build_retrieval_candidate_cache_key",
    "get_cached_retrieval_candidates",
    "set_cached_retrieval_candidates",
]
