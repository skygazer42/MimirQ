"""
In-memory KG search cache (best-effort, per-process).

Goal:
- Avoid repeated recall/expand/rerank work for identical KG search requests over a short TTL
  (e.g., query expansion + chunk injection in the same chat flow).

Security posture:
- Disabled by default (explicit opt-in).
- Cache key binds to (tenant, account, scope, query, and search config) but is stored as a hash
  to avoid leaking query text or scope identifiers in cache keys.
- Per-process only: safe even without Redis.
"""


import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from app.rag.core.hashing import stable_hash


def _hash_doc_scope(document_ids: list[str]) -> str:
    joined = ",".join(sorted(str(d) for d in (document_ids or []) if str(d or "").strip()))
    # Use a longer digest than the default short IDs to keep collisions vanishingly unlikely.
    return stable_hash(joined, length=32)


def build_kg_search_cache_key(
    *,
    tenant_id: str,
    account_id: str | None,
    dataset_id: str | None,
    document_ids: list[str] | None,
    pipeline_fingerprint: str | None = None,
    query: str,
    search_config: dict[str, Any] | None,
) -> str:
    """
    Build a short, stable cache key for a KG search request.

    Notes:
    - We hash the signature to avoid storing raw query text / scope identifiers in key names.
    - `search_config` should include any settings/params that can affect results.
    """
    doc_ids = [str(d) for d in (document_ids or []) if str(d or "").strip()]
    pipeline_fp = str(pipeline_fingerprint or "").strip() or None

    signature: dict[str, Any] = {
        # Bump when signature fields change to avoid accidental collisions.
        "v": 2,
        "tenant_id": str(tenant_id),
        "account_id": str(account_id or ""),
        "dataset_id": str(dataset_id or "") or None,
        "doc_scope": _hash_doc_scope(doc_ids),
        "doc_count": int(len(doc_ids)),
        # Hash of doc_id -> active_pipeline_hash (or pipeline_hash fallback) pairs.
        # This avoids serving stale results when a document switches its active pipeline version.
        "pipeline_fp": pipeline_fp,
        "query": (query or "").strip(),
        "cfg": (search_config if isinstance(search_config, dict) else None) or {},
    }

    raw = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = stable_hash(raw, length=32)
    # Keep prefix constant so different deployments can share env var knobs without changing semantics.
    return f"kgsearch:{tenant_id}:{digest}"


@dataclass(frozen=True)
class KGSearchCacheEntry:
    created_at_monotonic: float
    value: dict[str, Any]


class KGSearchCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, KGSearchCacheEntry]" = OrderedDict()

    def _purge_expired_locked(self, *, now: float, ttl_sec: int) -> None:
        if ttl_sec <= 0 or not self._entries:
            return
        expired: list[str] = []
        for key, entry in self._entries.items():
            if now - float(entry.created_at_monotonic) > float(ttl_sec):
                expired.append(key)
        for key in expired:
            self._entries.pop(key, None)

    def get(self, key: str, *, ttl_sec: int) -> tuple[dict[str, Any] | None, int | None]:
        if not key:
            return None, None
        if int(ttl_sec or 0) <= 0:
            return None, None
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now=now, ttl_sec=int(ttl_sec))
            entry = self._entries.get(key)
            if entry is None:
                return None, None
            # LRU bump
            self._entries.move_to_end(key, last=True)
            age_ms = int(max(0.0, (now - float(entry.created_at_monotonic)) * 1000.0))
            return dict(entry.value), age_ms

    def set(self, key: str, value: dict[str, Any], *, ttl_sec: int, max_entries: int) -> None:
        if not key:
            return
        if int(ttl_sec or 0) <= 0:
            return
        cap = int(max_entries or 0)
        if cap <= 0:
            return

        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now=now, ttl_sec=int(ttl_sec))
            self._entries[key] = KGSearchCacheEntry(created_at_monotonic=now, value=dict(value or {}))
            self._entries.move_to_end(key, last=True)
            while len(self._entries) > cap:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def size(self) -> int:
        with self._lock:
            return int(len(self._entries))


kg_search_cache = KGSearchCache()


def build_kg_community_summary_cache_key(*, community_id: str, query: str) -> str:
    """
    Build a stable key for query-aware community summaries.
    """
    signature = {
        "v": 1,
        "community_id": str(community_id or "").strip(),
        "query": str(query or "").strip(),
    }
    raw = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"kgcomm:{stable_hash(raw, length=32)}"


class KGCommunitySummaryCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, tuple[str, float]]" = OrderedDict()

    def _purge_expired_locked(self, *, now: float, ttl_sec: int) -> None:
        if ttl_sec <= 0 or not self._entries:
            return
        expired: list[str] = []
        for key, (_value, created_at) in self._entries.items():
            if now - float(created_at) > float(ttl_sec):
                expired.append(key)
        for key in expired:
            self._entries.pop(key, None)

    def get(self, key: str, *, ttl_sec: int) -> tuple[str | None, int | None]:
        if not key or int(ttl_sec or 0) <= 0:
            return None, None
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now=now, ttl_sec=int(ttl_sec))
            entry = self._entries.get(key)
            if entry is None:
                return None, None
            value, created_at = entry
            self._entries.move_to_end(key, last=True)
            age_ms = int(max(0.0, (now - float(created_at)) * 1000.0))
            return str(value), age_ms

    def set(self, key: str, value: str, *, ttl_sec: int, max_entries: int) -> None:
        if not key or not str(value or "").strip():
            return
        if int(ttl_sec or 0) <= 0:
            return
        cap = int(max_entries or 0)
        if cap <= 0:
            return
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now=now, ttl_sec=int(ttl_sec))
            self._entries[key] = (str(value), now)
            self._entries.move_to_end(key, last=True)
            while len(self._entries) > cap:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def size(self) -> int:
        with self._lock:
            return int(len(self._entries))


kg_community_summary_cache = KGCommunitySummaryCache()


__all__ = [
    "build_kg_community_summary_cache_key",
    "KGSearchCache",
    "KGSearchCacheEntry",
    "KGCommunitySummaryCache",
    "build_kg_search_cache_key",
    "kg_community_summary_cache",
    "kg_search_cache",
]
