"""
Integrated pipeline chunkers package.

Important: keep imports lazy.

Some chunkers depend on optional parsers/vision helpers and historically had circular
imports (e.g. book -> chunkers -> book). This module exposes a stable API without
importing all chunkers eagerly.
"""


from collections.abc import Callable
from importlib import import_module
from typing import Any


def _load_chunker(name: str) -> Callable[..., Any]:
    mod = import_module(f"app.third_party.integrated_pipeline.chunkers.{name}")
    fn = getattr(mod, "chunk", None)
    if fn is None:
        raise ImportError(f"integrated chunker '{name}' does not export chunk()")
    return fn


def naive_chunk(*args: Any, **kwargs: Any):  # noqa: ANN201
    return _load_chunker("naive")(*args, **kwargs)


def book_chunk(*args: Any, **kwargs: Any):  # noqa: ANN201
    return _load_chunker("book")(*args, **kwargs)


def laws_chunk(*args: Any, **kwargs: Any):  # noqa: ANN201
    return _load_chunker("laws")(*args, **kwargs)


def email_chunk(*args: Any, **kwargs: Any):  # noqa: ANN201
    return _load_chunker("email")(*args, **kwargs)


def get_chunker(strategy: str) -> Callable[..., Any]:
    """Get the chunker function for a given strategy.

    Args:
        strategy: One of 'naive', 'book', 'laws', 'email'

    Returns:
        The chunk function for that strategy

    Raises:
        ValueError: If strategy not supported
    """
    strat = str(strategy or "").strip().lower()
    if strat == "naive":
        return _load_chunker("naive")
    if strat == "book":
        return _load_chunker("book")
    if strat == "laws":
        return _load_chunker("laws")
    if strat == "email":
        return _load_chunker("email")

    raise ValueError(f"Unknown chunker strategy: {strategy}")


__all__ = [
    "naive_chunk",
    "book_chunk",
    "laws_chunk",
    "email_chunk",
    "get_chunker",
]

