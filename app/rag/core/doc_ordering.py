
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar('T')


def reorder_docs_for_generation(items: Sequence[T]) -> list[T]:
    """Interleave the ranked list so highly relevant items avoid clustering only at the front."""
    ordered = list(items)
    if len(ordered) < 3:
        return ordered
    front = ordered[::2]
    back = list(reversed(ordered[1::2]))
    return front + back


__all__ = ['reorder_docs_for_generation']
