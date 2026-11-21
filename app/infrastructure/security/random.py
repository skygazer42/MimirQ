"""
Cryptographically-secure randomness helpers.

These utilities exist primarily to avoid security hotspots caused by the standard
`random` module (PRNG). They are appropriate for jitter/backoff and sampling when
cryptographic unpredictability is desired or required by static analysis rules.
"""

from collections.abc import Sequence
from secrets import SystemRandom
from typing import TypeVar

T = TypeVar("T")
_RANDOM = SystemRandom()


def secure_random_float01() -> float:
    """Return a uniform float in [0.0, 1.0) using OS entropy."""
    return _RANDOM.random()


def secure_jitter(jitter: float) -> float:
    """Return a random jitter term for a positive bound, or zero."""
    if jitter <= 0.0:
        return 0.0
    return secure_random_float01() * jitter


def secure_sample(population: Sequence[T], k: int) -> list[T]:
    """Sample k items without replacement using OS entropy."""
    return _RANDOM.sample(list(population), k)
