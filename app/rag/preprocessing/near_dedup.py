"""
Cross-document near-duplicate helpers (best-effort).

This module maintains a lightweight SimHash bucket index on disk to detect
near-duplicate chunks across documents within the same tenant/dataset.

Design goals:
- No database schema changes
- Safe-by-default (opt-in)
- Best-effort concurrency safety (fcntl lock on Linux)
"""

import json
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.rag.core.logging import get_logger
from app.rag.preprocessing.simhash import hamming_distance64

logger = get_logger(__name__)

INDEX_VERSION = 1


@dataclass(frozen=True)
class NearDedupMatch:
    simhash64: str
    distance: int


def _safe_int_hex(value: str) -> int | None:
    try:
        return int(value.strip(), 16)
    except ValueError:
        return None


def _normalize_bucket_items(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    items: list[str] = []
    for item in values:
        if isinstance(item, str) and item.strip():
            items.append(item.strip().lower())
    return items


def _load_bucket_payload(data: object) -> dict[str, object] | None:
    if not isinstance(data, dict):
        return None
    if int(data.get("version") or 0) != INDEX_VERSION:
        return None
    buckets = data.get("buckets")
    return buckets if isinstance(buckets, dict) else None


def bucket_keys_for_simhash(simhash64_hex: str) -> list[str]:
    """Split 64-bit simhash into 4x16-bit buckets."""
    val = _safe_int_hex(simhash64_hex)
    if val is None:
        return []
    keys: list[str] = []
    for band in range(4):
        part = (val >> (band * 16)) & 0xFFFF
        keys.append(f"{band}:{part:04x}")
    return keys


@contextmanager
def _file_lock(lock_path: Path) -> Iterator[None]:
    """
    Best-effort advisory file lock (Linux).

    Unsupported platforms and OS lock failures continue without locking.
    """
    try:
        import fcntl  # type: ignore
    except ImportError:
        yield
        return

    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("a+", encoding="utf-8")
    except OSError as exc:
        logger.debug("Near-dedup lock file unavailable: %s", type(exc).__name__)
        yield
        return

    with lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            logger.debug("Near-dedup advisory lock unavailable: %s", type(exc).__name__)
            yield
            return
        try:
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError as exc:
                logger.debug("Ignoring near-dedup file lock release failure: %s", exc)


def load_near_dedup_index(path: Path) -> dict[str, list[str]]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    buckets = _load_bucket_payload(data)
    if buckets is None:
        return {}

    out: dict[str, list[str]] = {}
    for k, v in buckets.items():
        if not isinstance(k, str):
            continue
        items = _normalize_bucket_items(v)
        if items:
            out[k] = items
    return out


def save_near_dedup_index(path: Path, buckets: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": INDEX_VERSION,
        "updated_at": int(time.time()),
        "buckets": buckets,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def find_near_duplicate(
    *,
    buckets: dict[str, list[str]],
    simhash64_hex: str,
    hamming_threshold: int,
    max_bucket_size: int,
) -> NearDedupMatch | None:
    target_int = _safe_int_hex(simhash64_hex)
    if target_int is None:
        return None

    threshold = max(0, hamming_threshold)
    best: NearDedupMatch | None = None
    for key in bucket_keys_for_simhash(simhash64_hex):
        candidates = buckets.get(key) or []
        if max_bucket_size > 0:
            candidates = candidates[-max_bucket_size:]
        for cand_hex in candidates:
            cand_int = _safe_int_hex(cand_hex)
            if cand_int is None:
                continue
            dist = hamming_distance64(target_int, cand_int)
            if dist <= threshold and (best is None or dist < best.distance):
                best = NearDedupMatch(simhash64=cand_hex, distance=dist)
                if dist == 0:
                    return best
    return best


def add_simhashes(
    *,
    buckets: dict[str, list[str]],
    simhashes: Iterable[str],
    max_bucket_size: int,
) -> dict[str, list[str]]:
    max_bucket_size_eff = max(0, max_bucket_size)
    for sh in simhashes:
        sh_norm = sh.strip().lower()
        if not sh_norm:
            continue
        for key in bucket_keys_for_simhash(sh_norm):
            arr = buckets.setdefault(key, [])
            arr.append(sh_norm)
            if max_bucket_size_eff > 0 and len(arr) > max_bucket_size_eff:
                # Keep most recent items.
                buckets[key] = arr[-max_bucket_size_eff:]
    return buckets


def with_near_dedup_index(
    *,
    path: Path,
    fn: Callable[[dict[str, list[str]]], dict[str, list[str]] | None],
) -> dict[str, list[str]] | None:
    """
    Load-lock-update-save wrapper to keep the index file consistent.

    `fn` signature: (buckets: dict[str, list[str]]) -> dict[str, list[str]] | None
    - If it returns a dict, it's persisted.
    - If it returns None, nothing is written.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    with _file_lock(lock_path):
        buckets = load_near_dedup_index(path)
        updated = fn(buckets)
        if isinstance(updated, dict):
            save_near_dedup_index(path, updated)
        return updated


__all__ = [
    "INDEX_VERSION",
    "NearDedupMatch",
    "add_simhashes",
    "bucket_keys_for_simhash",
    "find_near_duplicate",
    "load_near_dedup_index",
    "save_near_dedup_index",
    "with_near_dedup_index",
]
