"""
SimHash fingerprinting utilities.

Used for:
- per-chunk near-duplicate fingerprints (metadata)
- optional cross-document near-duplicate dropping
"""


import hashlib
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")


def simhash64(text: str) -> int:
    """
    Compute a 64-bit SimHash for a piece of text.

    Notes:
    - Tokenization is intentionally simple (alnum/CJK runs).
    - Hashing uses BLAKE2b truncated to 64 bits for stability across processes.
    """
    raw = (text or "").strip()
    if not raw:
        return 0

    tokens = [t.casefold() for t in _TOKEN_RE.findall(raw)]
    if not tokens:
        return 0

    weights = Counter(tokens)
    vec = [0] * 64
    for tok, w in weights.items():
        digest = hashlib.blake2b(tok.encode("utf-8", "ignore"), digest_size=8).digest()
        h = int.from_bytes(digest, "big", signed=False)
        weight = int(w) if w else 1
        for i in range(64):
            vec[i] += weight if (h >> i) & 1 else -weight

    out = 0
    for i, val in enumerate(vec):
        if val >= 0:
            out |= 1 << i
    return out


def hamming_distance64(a: int, b: int) -> int:
    return int((int(a) ^ int(b)).bit_count())


def simhash64_hex(value: int) -> str:
    return f"{int(value) & ((1 << 64) - 1):016x}"


__all__ = [
    "hamming_distance64",
    "simhash64",
    "simhash64_hex",
]
