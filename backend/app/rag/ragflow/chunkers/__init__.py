"""
Ragflow chunkers package.
Provides document chunking functionality from ragflow.

Note: Some advanced features (LLM-based parsing, hyperlink extraction)
require additional ragflow dependencies that may not be available.
"""

# Import chunk functions with graceful fallback
try:
    from app.rag.ragflow.chunkers.naive import chunk as naive_chunk
except ImportError as e:
    naive_chunk = None
    _naive_error = str(e)

try:
    from app.rag.ragflow.chunkers.book import chunk as book_chunk
except ImportError as e:
    book_chunk = None
    _book_error = str(e)

try:
    from app.rag.ragflow.chunkers.laws import chunk as laws_chunk
except ImportError as e:
    laws_chunk = None
    _laws_error = str(e)

try:
    from app.rag.ragflow.chunkers.email import chunk as email_chunk
except ImportError as e:
    email_chunk = None
    _email_error = str(e)


def get_chunker(strategy: str):
    """Get the chunker function for a given strategy.

    Args:
        strategy: One of 'naive', 'book', 'laws', 'email'

    Returns:
        The chunk function for that strategy

    Raises:
        ValueError: If strategy not supported
        ImportError: If chunker dependencies not available
    """
    chunkers = {
        'naive': (naive_chunk, getattr(globals(), '_naive_error', None)),
        'book': (book_chunk, getattr(globals(), '_book_error', None)),
        'laws': (laws_chunk, getattr(globals(), '_laws_error', None)),
        'email': (email_chunk, getattr(globals(), '_email_error', None)),
    }

    if strategy not in chunkers:
        raise ValueError(f"Unknown chunker strategy: {strategy}")

    func, error = chunkers[strategy]
    if func is None:
        raise ImportError(f"Chunker '{strategy}' not available: {error}")

    return func


__all__ = [
    'naive_chunk',
    'book_chunk',
    'laws_chunk',
    'email_chunk',
    'get_chunker',
]
