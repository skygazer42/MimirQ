"""
In-memory caches used by preview endpoints.

Goal: speed up interactive tuning on large documents by avoiding repeated parsing.
Scope: best-effort, per-process only (works even without Redis).
"""


import asyncio
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParseCacheEntry:
    created_at_monotonic: float
    created_at_wall: float
    file_sha256: str
    parser_backend: str
    resolved_backend: str
    documents: list[dict[str, Any]]
    total_chars: int


class PreviewParseCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, ParseCacheEntry]" = OrderedDict()

    def _purge_expired_locked(self, *, now: float, ttl_sec: int) -> None:
        if ttl_sec <= 0 or not self._entries:
            return
        expired: list[str] = []
        for key, entry in self._entries.items():
            if now - entry.created_at_monotonic > ttl_sec:
                expired.append(key)
        for key in expired:
            self._entries.pop(key, None)

    def get(self, key: str, *, ttl_sec: int) -> tuple[ParseCacheEntry | None, int | None]:
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now=now, ttl_sec=ttl_sec)
            entry = self._entries.get(key)
            if entry is None:
                return None, None
            # LRU bump
            self._entries.move_to_end(key, last=True)
            age_ms = int(max(0.0, (now - entry.created_at_monotonic) * 1000.0))
            return entry, age_ms

    def set(self, key: str, entry: ParseCacheEntry, *, ttl_sec: int, max_entries: int) -> None:
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now=now, ttl_sec=ttl_sec)
            self._entries[key] = entry
            self._entries.move_to_end(key, last=True)
            # LRU eviction
            cap = int(max_entries or 0)
            if cap > 0:
                while len(self._entries) > cap:
                    self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._entries)


preview_parse_cache = PreviewParseCache()


class PreviewParseLocks:
    """
    Keyed async locks to avoid stampeding when multiple requests preview the same file.

    Notes:
    - Best-effort, per-process only.
    - Locks are bounded with a small LRU to avoid unbounded growth.
    - Locks are created lazily inside an active event loop.
    """

    def __init__(self, *, max_locks: int = 128) -> None:
        self._lock = threading.Lock()
        self._locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()
        self._max_locks = int(max_locks or 0) or 128

    def get(self, key: str) -> asyncio.Lock | None:
        if not key:
            return None
        with self._lock:
            lock = self._locks.get(key)
            if lock is None:
                try:
                    lock = asyncio.Lock()
                except RuntimeError:
                    # No running loop (shouldn't happen inside FastAPI request context).
                    return None
                self._locks[key] = lock
            self._locks.move_to_end(key, last=True)
            while len(self._locks) > self._max_locks:
                self._locks.popitem(last=False)
            return lock


preview_parse_locks = PreviewParseLocks()
