"""
Evidence post-rerank result cache (in-memory, short TTL, best-effort).

Goal:
- Avoid repeated cross-encoder / LTR reranking work for identical evidence requests
  over a short time window (e.g., UI refresh, retry, offline replay loops).

Security posture:
- Disabled by default
- Cache keys are stable hashes; no raw query text or chunk text is persisted
- Cache values store only ordered ids + numeric scores (PII-safe identifiers only)
"""


import json
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from app.core.config import settings
from app.core.redis_client import LazyRedisClient
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.embedding.utils import current_embedding_space_hash
from app.rag.reranker.types import RerankCandidate, RerankResult

logger = get_logger("rag.evidence_rerank_cache")

_META_ALLOWLIST = {
    # Scores / channel signals (numeric)
    "score",
    "vector_score",
    "bm25_score",
    "lexical_score",
    "sparse_score",
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


def _normalize_provider(provider: str | None) -> str:
    p = str(provider or "").strip().lower()
    if p in {"cross-encoder", "sentence_transformers", "sentence-transformers"}:
        return "cross_encoder"
    if p in {"xgboost_ltr"}:
        return "ltr"
    if p in {"late_interaction"}:
        return "colbert"
    return p or "unknown"


def _provider_version_signature(provider: str | None) -> dict[str, Any]:
    """
    Build low-cardinality provider-version signature for cache keying.

    The signature intentionally excludes secrets and query/candidate text.
    """
    normalized = _normalize_provider(provider)
    sig: dict[str, Any] = {"provider": normalized}

    if normalized == "ltr":
        sig.update(
            {
                "ltr_model_path": str(getattr(settings, "LTR_MODEL_PATH", "") or ""),
                "ltr_manifest_path": str(getattr(settings, "LTR_MODEL_MANIFEST_PATH", "") or ""),
                "ltr_feature_spec_version": int(getattr(settings, "LTR_FEATURE_SPEC_VERSION", 1) or 1),
            }
        )
        return sig

    if normalized == "colbert":
        sig.update(
            {
                "colbert_provider": str(getattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic") or "deterministic")
                .strip()
                .lower(),
                "colbert_model_name": str(getattr(settings, "COLBERT_RERANK_MODEL_NAME", "") or ""),
                "colbert_device": str(getattr(settings, "COLBERT_RERANK_DEVICE", "cpu") or "cpu").strip().lower(),
                "colbert_batch_size": int(getattr(settings, "COLBERT_RERANK_BATCH_SIZE", 16) or 16),
                "colbert_max_length": int(getattr(settings, "COLBERT_RERANK_MAX_LENGTH", 256) or 256),
                "colbert_embed_dim": int(getattr(settings, "COLBERT_RERANK_EMBED_DIM", 64) or 64),
            }
        )
        return sig

    if normalized == "cross_encoder":
        sig.update(
            {
                "reranker_model": str(getattr(settings, "RERANKER_MODEL", "") or ""),
            }
        )
        return sig

    sig.update(
        {
            "reranker_model": str(getattr(settings, "RERANKER_MODEL", "") or ""),
            "reranker_api_base": str(getattr(settings, "RERANKER_API_BASE", "") or ""),
        }
    )
    return sig


def _normalize_meta_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        # Keep deterministic fingerprints while remaining tolerant of tiny fp jitter.
        return round(float(value), 6)
    try:
        # Best-effort: preserve deterministic string representation.
        return str(value)
    except Exception:
        return None


def _fingerprint_candidate_entry(candidate: RerankCandidate) -> dict[str, Any] | None:
    if candidate is None:
        return None
    cid = str(getattr(candidate, "id", "") or "").strip()
    if not cid:
        return None
    meta = getattr(candidate, "metadata", None)
    meta = meta if isinstance(meta, dict) else {}

    entry: dict[str, Any] = {"id": cid}
    for key in _META_KEYS_SORTED:
        if key not in meta:
            continue
        nv = _normalize_meta_value(meta.get(key))
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
    provider_norm = _normalize_provider(provider)
    sig = {
        "schema": str(schema or "").strip() or "mimirq.evidence_post_rerank_cache.v1",
        "provider": provider_norm,
        "top_n": int(top_n or 0),
        "query_hash": stable_hash((query or "").strip(), length=16),
        "candidates": str(candidates_fingerprint or ""),
        "corpus_cache_token": str(corpus_cache_token or "") or None,
        "embedding_space_hash": str(current_embedding_space_hash() or "") or None,
        "tenant_hash": stable_hash(str(tenant_id or ""), length=16),
        "account_hash": stable_hash(str(account_id or ""), length=16),
        # Provider/model/spec identity so cache entries do not cross incompatible reranker versions.
        "provider_version": _provider_version_signature(provider_norm),
    }
    raw = json.dumps(sig, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = stable_hash(raw, length=32)
    prefix = str(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_PREFIX", "eprr") or "eprr").strip() or "eprr"
    return f"{prefix}:{digest}"


class _TTLCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: "OrderedDict[str, tuple[dict[str, Any], float]]" = OrderedDict()

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def _ttl_sec(self) -> float:
        return float(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_TTL_SEC", 0) or 0)

    def _max_entries(self) -> int:
        return max(0, int(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES", 0) or 0))

    def _enabled(self) -> bool:
        return bool(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", False)) and self._max_entries() > 0

    def get(self, key: str) -> dict[str, Any] | None:
        if not key or not self._enabled():
            return None
        now = time.time()
        ttl = self._ttl_sec()
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
        if not key or not self._enabled():
            return False
        max_entries = self._max_entries()
        if max_entries <= 0:
            return False
        now = time.time()
        with self._lock:
            self._data[key] = (dict(payload), now)
            self._data.move_to_end(key, last=True)
            while len(self._data) > max_entries:
                self._data.popitem(last=False)
        return True

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())


_CACHE = _TTLCache()


def get_evidence_post_rerank_cache_backend() -> str:
    backend = str(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_BACKEND", "memory") or "memory").strip().lower()
    if backend not in {"memory", "redis"}:
        return "memory"
    return backend


def _get_cached_payload_from_redis(key: str) -> dict[str, Any] | None:
    if not key or not bool(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", False)):
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
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def _set_cached_payload_to_redis(key: str, payload: dict[str, Any]) -> bool:
    if not key or not bool(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", False)):
        return False
    client = _get_redis_client()
    if client is None:
        return False
    ttl = int(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_TTL_SEC", 0) or 0)
    try:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    except Exception:  # noqa: BLE001
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
    if not isinstance(payload, dict):
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
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue

    if not ordered_ids:
        return None

    return RerankResult(
        ordered_ids=ordered_ids,
        score_map=score_map_out,
        elapsed_sec=0.0,
        provider=str(payload.get("provider") or "") or None,
        model_used=str(payload.get("model_used") or "") or None,
        stats={"cache_hit": True},
    )


def set_cached_evidence_post_rerank_result(key: str, result: RerankResult) -> bool:
    if not key or result is None:
        return False
    payload: dict[str, Any] = {
        "ordered_ids": list(result.ordered_ids or []),
        "score_map": dict(result.score_map or {}),
        "provider": result.provider,
        "model_used": result.model_used,
        "schema": "mimirq.rerank_result_cache_item.v1",
    }
    backend = get_evidence_post_rerank_cache_backend()
    if backend == "redis":
        return bool(_set_cached_payload_to_redis(key, payload))
    return bool(_CACHE.set(key, payload))


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
