"""
RAGFlow pipeline bridge.

Provides a canonical entry point for RAGFlow chunking strategies.
These strategies handle parsing + chunking as an integrated pipeline.

Available strategies:
- ragflow_naive: General-purpose chunking
- ragflow_book: Book format (chapter/section aware)
- ragflow_laws: Legal document format
- ragflow_email: Email format
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Literal, Optional, Any

from app.rag.core.logging import get_logger

ChunkStrategy = Literal["ragflow_naive", "ragflow_book", "ragflow_laws", "ragflow_email"]


logger = get_logger("ragflow.bridge")


def chunk_file(
    file_path: Path,
    *,
    strategy: ChunkStrategy,
    binary: Optional[bytes] = None,
    callback: Optional[Callable] = None,
    **kwargs: Any,
) -> List[dict]:
    """
    Process a file using RAGFlow chunking pipeline.

    Args:
        file_path: Path to the file to process.
        strategy: RAGFlow strategy to use.
        binary: Optional file binary content (if already loaded).
        callback: Progress callback function(progress, message).
        **kwargs: Additional arguments passed to the chunker.

    Returns:
        List of chunk dictionaries from RAGFlow pipeline.

    Raises:
        ValueError: If strategy is not supported.
    """
    strat = strategy.lower()

    if strat == "ragflow_naive":
        from app.rag.chunking.ragflow.chunkers.naive import chunk as rf_chunk
    elif strat == "ragflow_book":
        from app.rag.chunking.ragflow.chunkers.book import chunk as rf_chunk
    elif strat == "ragflow_laws":
        from app.rag.chunking.ragflow.chunkers.laws import chunk as rf_chunk
    elif strat == "ragflow_email":
        from app.rag.chunking.ragflow.chunkers.email import chunk as rf_chunk
    else:
        raise ValueError(
            f"Unsupported RAGFlow strategy: {strategy}. "
            f"Supported: ragflow_naive, ragflow_book, ragflow_laws, ragflow_email"
        )

    if callback is None:
        def callback(prog=None, msg=""):
            if msg:
                logger.info("[ragflow] %s (%s)", msg, prog)

    return rf_chunk(str(file_path), binary=binary, callback=callback, **kwargs)
