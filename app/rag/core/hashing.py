"""
Stable hashing helpers (PII-safe).

Why:
- Python's built-in `hash()` is salted per-process, so it is not stable across restarts.
- For RAG replay/debug/eval, we want deterministic IDs/keys when we fall back to hashing.
"""


import hashlib
import hmac
import json
from typing import Any


def stable_hash(text: str, *, length: int | None = 16) -> str:
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


def stable_hmac(text: str, *, secret: str, length: int = 32) -> str:
    """
    Return a stable HMAC-SHA256 lowercase hex digest for `text`.

    Notes:
    - Uses caller-provided secret (must be non-empty).
    - `length` truncates the digest for compact signatures.
    """
    key = (secret or "").encode("utf-8", "ignore")
    if not key:
        return ""
    raw = (text or "").encode("utf-8", "ignore")
    digest = hmac.new(key, raw, hashlib.sha256).hexdigest()
    n = int(length or 0)
    if n <= 0:
        return digest
    return digest[:n]


def stable_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_json_hash(value: Any, *, length: int = 16) -> str:
    return stable_hash(stable_json_dumps(value), length=length)


def stable_json_hmac(value: Any, *, secret: str, length: int = 32) -> str:
    return stable_hmac(stable_json_dumps(value), secret=secret, length=length)


__all__ = [
    "stable_hash",
    "stable_hmac",
    "stable_json_dumps",
    "stable_json_hash",
    "stable_json_hmac",
]
