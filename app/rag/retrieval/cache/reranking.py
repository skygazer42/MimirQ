"""
Evidence post-rerank result cache (memory or Redis, short TTL, best-effort).

Goal:
- Avoid repeated supported reranking work for identical evidence requests
  over a short time window (e.g., UI refresh, retry, offline replay loops).

Security posture:
- Disabled by default
- Cache keys are stable hashes; no raw query text or chunk text is persisted
- Cache values store only ordered ids + numeric scores (PII-safe identifiers only)
"""

import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from app.infrastructure.config import settings
from app.infrastructure.hashing import stable_hash
from app.infrastructure.model_policy import reject_retired_provider
from app.infrastructure.redis.client import LazyRedisClient
from app.rag.embedding.utils import current_embedding_space_hash
from app.rag.retrieval.reranking.types import RerankCandidate, RerankResult

logger = logging.getLogger("rag.evidence_rerank_cache")

_META_ALLOWLIST = {
    # Scores / channel signals (numeric)
    "score",
    "vector_score",
    "bm25_score",
    "lexical_score",
    "keyword_score",
    "retrieval_score",
    # Provenance / low-cardinality flags
    "retrieval_role",
    "kg_pagerank",
    "kg_path_length",
    "kg_shared_events",
    "kg_evidence_anchored",
    "kg_edge_conf_low",
    "kg_edge_conf_mid",
    "kg_edge_conf_high",
}
_META_KEYS_SORTED = tuple(sorted(_META_ALLOWLIST))
_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": False,
    },
    on_error=lambda exc: logger.warning(
        "Evidence post-rerank cache redis backend unavailable: %s",
        str(exc)[:200],
    ),
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate


def _normalize_meta_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        # Keep deterministic fingerprints while remaining tolerant of tiny fp jitter.
        return round(float(value), 6)
    return str(value)


def _fingerprint_candidate_entry(candidate: RerankCandidate) -> dict[str, Any] | None:
    cid = candidate.id.strip()
    if not cid:
        return None
    meta = candidate.metadata

    entry: dict[str, Any] = {"id": cid}
    for key in _META_KEYS_SORTED:
        if key not in meta:
            continue
        nv = _normalize_meta_value(meta[key])
        if nv is None:
            continue
        entry[key] = nv
    return entry


def fingerprint_rerank_candidates(candidates: Sequence[RerankCandidate]) -> str:
    """
    Build a PII-safe fingerprint for rerank inputs.

    Important: this must not depend on candidate text content.
    """
    items: list[dict[str, Any]] = []
    for c in candidates:
        entry = _fingerprint_candidate_entry(c)
        if entry is not None:
            items.append(entry)

    raw = json.dumps(items, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return stable_hash(raw, length=32)


def build_evidence_post_rerank_cache_key(
    *,
    tenant_id: Any | None,
    account_id: Any | None,
    provider: str,
    top_n: int,
    query: str,
    candidates_fingerprint: str,
    corpus_cache_token: str | None = None,
    schema: str = "mimirq.evidence_post_rerank_cache.v1",
) -> str:
    """
    Build a stable, PII-safe cache key for an evidence post-rerank call.

    Notes:
    - `query` is hashed (not stored).
    - `tenant_id` / `account_id` are included only as hashed components (not stored).
    """
    provider_norm = provider.strip().lower()
    reject_retired_provider(provider_norm, capability="reranker")
    provider_norm = provider_norm or "unknown"
    sig = {
        "schema": schema.strip(),
        "provider": provider_norm,
        "top_n": int(top_n),
        "query_hash": stable_hash(query.strip(), length=16),
        "candidates": candidates_fingerprint,
        "corpus_cache_token": corpus_cache_token,
        "embedding_space_hash": current_embedding_space_hash(),
        "tenant_hash": stable_hash(str((tenant_id if tenant_id is not None else "")), length=16),
        "account_hash": stable_hash(str((account_id if account_id is not None else "")), length=16),
        # Provider/model/spec identity so cache entries do not cross incompatible reranker versions.
        "provider_version": {
            "provider": provider_norm,
            "reranker_model": settings.RERANKER_MODEL,
            "reranker_api_base": settings.RERANKER_API_BASE,
        },
    }
    raw = json.dumps(sig, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = stable_hash(raw, length=32)
    prefix = str(settings.EVIDENCE_POST_RERANK_CACHE_PREFIX).strip() or "eprr"
    return f"{prefix}:{digest}"


class _TTLCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: "OrderedDict[str, tuple[dict[str, Any], float]]" = OrderedDict()

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def get(self, key: str) -> dict[str, Any] | None:
        if not key or not settings.EVIDENCE_POST_RERANK_CACHE_ENABLED:
            return None
        if settings.EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES <= 0:
            return None
        now = time.time()
        ttl = settings.EVIDENCE_POST_RERANK_CACHE_TTL_SEC
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            payload, ts = item
            if ttl > 0 and (now - ts) > ttl:
                self._data.pop(key, None)
                return None
            # LRU bump
            self._data.move_to_end(key, last=True)
            return dict(payload)

    def set(self, key: str, payload: dict[str, Any]) -> bool:
        if not key or not settings.EVIDENCE_POST_RERANK_CACHE_ENABLED:
            return False
        max_entries = settings.EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES
        if max_entries <= 0:
            return False
        now = time.time()
        with self._lock:
            self._data[key] = (dict(payload), now)
            self._data.move_to_end(key, last=True)
            while len(self._data) > max_entries:
                self._data.popitem(last=False)
        return True


_CACHE = _TTLCache()


def get_evidence_post_rerank_cache_backend() -> str:
    return settings.EVIDENCE_POST_RERANK_CACHE_BACKEND


def _get_cached_payload_from_redis(key: str) -> dict[str, Any] | None:
    if not key or not settings.EVIDENCE_POST_RERANK_CACHE_ENABLED:
        return None
    client = _get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Evidence post-rerank cache read failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        logger.debug("Evidence post-rerank cache payload could not be decoded (%s)", type(exc).__name__)
        return None
    return payload if isinstance(payload, dict) else None


def _set_cached_payload_to_redis(key: str, payload: dict[str, Any]) -> bool:
    if not key or not settings.EVIDENCE_POST_RERANK_CACHE_ENABLED:
        return False
    client = _get_redis_client()
    if client is None:
        return False
    ttl = int(settings.EVIDENCE_POST_RERANK_CACHE_TTL_SEC)
    try:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        logger.warning("Evidence post-rerank cache payload could not be serialized (%s)", type(exc).__name__)
        return False
    try:
        if ttl > 0:
            client.set(key, raw, ex=ttl)
        else:
            client.set(key, raw)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Evidence post-rerank cache write failed: %s", str(exc)[:200])
        _invalidate_redis_client()
        return False


def get_cached_evidence_post_rerank_result(key: str) -> RerankResult | None:
    backend = get_evidence_post_rerank_cache_backend()
    if backend == "redis":
        payload = _get_cached_payload_from_redis(key)
    else:
        payload = _CACHE.get(key)
    if payload is None:
        return None

    ordered = payload.get("ordered_ids")
    score_map = payload.get("score_map")
    if not isinstance(ordered, list) or not isinstance(score_map, dict):
        return None

    ordered_ids: list[str] = []
    for x in ordered:
        if isinstance(x, str) and x.strip():
            ordered_ids.append(x.strip())

    score_map_out: dict[str, float] = {}
    for k, v in score_map.items():
        if not isinstance(k, str) or not k.strip():
            continue
        try:
            score_map_out[k.strip()] = float(v)
        except (TypeError, ValueError, OverflowError):
            logging.getLogger("app.rag.rerank_result_cache").debug(
                "Skipping item after non-critical exception", exc_info=True
            )
            continue

    if not ordered_ids:
        return None

    return RerankResult(
        ordered_ids=ordered_ids,
        score_map=score_map_out,
        elapsed_sec=0.0,
        provider=payload["provider"],
        model_used=payload["model_used"],
        stats={"cache_hit": True},
    )


def set_cached_evidence_post_rerank_result(key: str, result: RerankResult) -> bool:
    if not key:
        return False
    payload: dict[str, Any] = {
        "ordered_ids": list(result.ordered_ids),
        "score_map": dict(result.score_map),
        "provider": result.provider,
        "model_used": result.model_used,
        "schema": "mimirq.rerank_result_cache_item.v1",
    }
    backend = get_evidence_post_rerank_cache_backend()
    if backend == "redis":
        return _set_cached_payload_to_redis(key, payload)
    return _CACHE.set(key, payload)


def clear_evidence_post_rerank_cache_for_tests() -> None:
    _CACHE.clear()
    _invalidate_redis_client()


def clear_evidence_post_rerank_cache() -> bool:
    _CACHE.clear()
    return True


__all__ = [
    "build_evidence_post_rerank_cache_key",
    "fingerprint_rerank_candidates",
    "get_evidence_post_rerank_cache_backend",
    "get_cached_evidence_post_rerank_result",
    "set_cached_evidence_post_rerank_result",
    "clear_evidence_post_rerank_cache",
    "clear_evidence_post_rerank_cache_for_tests",
]
