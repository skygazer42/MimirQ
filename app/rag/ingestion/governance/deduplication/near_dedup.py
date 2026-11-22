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
import logging
import os
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.rag.ingestion.governance.deduplication.simhash import hamming_distance64

logger = logging.getLogger("app.rag.ingestion.governance.deduplication.near_dedup")

# Version 1 could contain hashes registered before indexing succeeded.
# It cannot distinguish those entries from successfully indexed documents.
INDEX_VERSION = 2


@dataclass(frozen=True)
class NearDedupMatch:
    simhash64: str
    distance: int


class _NearDedupIndex(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)

    version: int
    buckets: dict[
        Annotated[str, Field(pattern=r"^[0-3]:[0-9a-f]{4}$")],
        list[Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[0-9a-fA-F]{16}$")]],
    ]


def bucket_keys_for_simhash(simhash64_hex: str) -> list[str]:
    """Split 64-bit simhash into 4x16-bit buckets."""
    val = int(simhash64_hex, 16)
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
    if os.name != "posix":
        yield
        return

    import fcntl

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
    try:
        payload = _NearDedupIndex.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return {}
    except (OSError, ValidationError) as exc:
        logger.warning("Near-dedup derived index could not be loaded: %s", type(exc).__name__)
        return {}
    if payload.version != INDEX_VERSION:
        logger.debug("Discarding near-dedup derived index version %s", payload.version)
        return {}
    return payload.buckets


def save_near_dedup_index(path: Path, buckets: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": INDEX_VERSION,
        "updated_at": int(time.time()),
        "buckets": buckets,
    }
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def find_near_duplicate(
    *,
    buckets: dict[str, list[str]],
    simhash64_hex: str,
    hamming_threshold: int,
    max_bucket_size: int,
) -> NearDedupMatch | None:
    target_int = int(simhash64_hex, 16)

    threshold = max(0, hamming_threshold)
    best: NearDedupMatch | None = None
    for key in bucket_keys_for_simhash(simhash64_hex):
        candidates = buckets.get(key, [])
        if max_bucket_size > 0:
            candidates = candidates[-max_bucket_size:]
        for cand_hex in candidates:
            cand_int = int(cand_hex, 16)
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
        if updated is not None:
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
