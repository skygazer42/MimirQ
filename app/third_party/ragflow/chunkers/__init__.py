"""
Ragflow chunkers package.
Provides document chunking functionality from ragflow.
"""

from app.third_party.ragflow.chunkers.book import chunk as book_chunk
from app.third_party.ragflow.chunkers.email import chunk as email_chunk
from app.third_party.ragflow.chunkers.laws import chunk as laws_chunk
from app.third_party.ragflow.chunkers.naive import chunk as naive_chunk


def get_chunker(strategy: str):
    """Get the chunker function for a given strategy.

    Args:
        strategy: One of 'naive', 'book', 'laws', 'email'

    Returns:
        The chunk function for that strategy

    Raises:
        ValueError: If strategy not supported
    """
    chunkers = {
        'naive': naive_chunk,
        'book': book_chunk,
        'laws': laws_chunk,
        'email': email_chunk,
    }

    if strategy not in chunkers:
        raise ValueError(f"Unknown chunker strategy: {strategy}")

    return chunkers[strategy]


__all__ = [
    'naive_chunk',
    'book_chunk',
    'laws_chunk',
    'email_chunk',
    'get_chunker',
]
