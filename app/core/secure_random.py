"""
Cryptographically-secure randomness helpers.

These utilities exist primarily to avoid security hotspots caused by the standard
`random` module (PRNG). They are appropriate for jitter/backoff and sampling when
cryptographic unpredictability is desired or required by static analysis rules.
"""

import secrets
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def secure_random_float01() -> float:
    """
    Return a uniform float in [0.0, 1.0) using OS entropy.

    Implementation detail:
    - Use 53 random bits to match the mantissa precision of IEEE-754 doubles.
    """
    return secrets.randbits(53) / (1 << 53)


def secure_jitter(jitter: float) -> float:
    """
    Return a jitter term in [0.0, jitter] (inclusive of 0.0, exclusive of jitter for float rounding).
    """
    jitter = jitter or 0.0
    if jitter <= 0.0:
        return 0.0
    return secure_random_float01() * jitter


def secure_sample(population: Sequence[T], k: int) -> list[T]:
    """
    Sample k distinct items from population without replacement using OS entropy.

    Mirrors `random.sample` semantics by raising when k > len(population).
    """
    items = list(population)
    n = len(items)
    if not 0 <= k <= n:
        raise ValueError("Sample larger than population or is negative")
    if k == 0:
        return []

    # Partial Fisher-Yates shuffle.
    for i in range(k):
        j = i + secrets.randbelow(n - i)
        items[i], items[j] = items[j], items[i]
    return items[:k]
