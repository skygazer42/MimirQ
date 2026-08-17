"""Lightweight evidence post-rerank cache for retrieval orchestration.

This mirrors the small surface used by the orchestrator without importing the
embedding package tree that pulls in unrelated runtime modules.
"""

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from app.core.config import settings
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.reranker.types import RerankCandidate, RerankResult

logger = get_logger("rag.evidence_rerank_cache")

_META_ALLOWLIST = {
    "score",
    "vector_score",
    "bm25_score",
    "lexical_score",
    "sparse_score",
    "keyword_score",
    "retrieval_score",
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


def current_embedding_space_hash(*, length: int | None = 16) -> str:
    provider = str(getattr(settings, "EMBEDDING_PROVIDER", "") or "").strip().lower()
    model = str(getattr(settings, "EMBEDDING_MODEL", "") or "").strip()
    base_url = str(getattr(settings, "EMBEDDING_API_BASE", "") or getattr(settings, "LLM_API_BASE", "") or "").strip()
    key = f"provider={provider}|model={model}|base_url={base_url.rstrip('/')}"
    return stable_hash(key, length=length or 16)


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
                "colbert_provider": str(
                    getattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic") or "deterministic"
                )
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
        sig.update({"reranker_model": str(getattr(settings, "RERANKER_MODEL", "") or "")})
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
        return round(float(value), 6)
    try:
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


_CACHE = _TTLCache()


def get_evidence_post_rerank_cache_backend() -> str:
    backend = str(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_BACKEND", "memory") or "memory").strip().lower()
    if backend not in {"memory", "redis"}:
        return "memory"
    return backend


def get_cached_evidence_post_rerank_result(key: str) -> RerankResult | None:
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
    return bool(_CACHE.set(key, payload))


def clear_evidence_post_rerank_cache_for_tests() -> None:
    _CACHE.clear()


def clear_evidence_post_rerank_cache() -> bool:
    _CACHE.clear()
    return True


__all__ = [
    "build_evidence_post_rerank_cache_key",
    "clear_evidence_post_rerank_cache",
    "clear_evidence_post_rerank_cache_for_tests",
    "fingerprint_rerank_candidates",
    "get_cached_evidence_post_rerank_result",
    "get_evidence_post_rerank_cache_backend",
    "set_cached_evidence_post_rerank_result",
]
