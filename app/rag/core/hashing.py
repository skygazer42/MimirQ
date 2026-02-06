"""
Stable hashing helpers (PII-safe).

Why:
- Python's built-in `hash()` is salted per-process, so it is not stable across restarts.
- For RAG replay/debug/eval, we want deterministic IDs/keys when we fall back to hashing.
"""

from __future__ import annotations

import hashlib


def stable_hash(text: str, *, length: int = 16) -> str:
    """
    Return a stable lowercase hex digest for `text`.

    Notes:
    - Uses SHA-256 (cryptographic; stable).
    - `length` truncates the digest for short IDs (default: 16 hex chars).
    """
    raw = (text or "").encode("utf-8", "ignore")
    digest = hashlib.sha256(raw).hexdigest()
    if length is None:
        return digest
    n = int(length or 0)
    if n <= 0:
        return digest
    return digest[:n]


__all__ = ["stable_hash"]

