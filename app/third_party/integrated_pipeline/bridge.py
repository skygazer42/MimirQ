"""
Integrated pipeline bridge.

Provides a canonical entry point for Integrated pipeline chunking strategies.
These strategies handle parsing + chunking as an integrated pipeline.

Available strategies:
- integrated_naive: General-purpose chunking
- integrated_book: Book format (chapter/section aware)
- integrated_laws: Legal document format
- integrated_email: Email format
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from app.rag.core.logging import get_logger

ChunkStrategy = Literal["integrated_naive", "integrated_book", "integrated_laws", "integrated_email"]


logger = get_logger("integrated.bridge")


def chunk_file(
    file_path: Path,
    *,
    strategy: ChunkStrategy,
    binary: bytes | None = None,
    callback: Callable | None = None,
    **kwargs: Any,
) -> list[dict]:
    """
    Process a file using the integrated parse+chunk pipeline.

    Args:
        file_path: Path to the file to process.
        strategy: Integrated pipeline strategy to use.
        binary: Optional file binary content (if already loaded).
        callback: Progress callback function(progress, message).
        **kwargs: Additional arguments passed to the chunker.

    Returns:
        List of chunk dictionaries produced by the integrated pipeline.

    Raises:
        ValueError: If strategy is not supported.
    """
    strat = strategy.lower()

    if strat == "integrated_naive":
        from app.third_party.integrated_pipeline.chunkers.naive import chunk as chunk_fn
    elif strat == "integrated_book":
        from app.third_party.integrated_pipeline.chunkers.book import chunk as chunk_fn
    elif strat == "integrated_laws":
        from app.third_party.integrated_pipeline.chunkers.laws import chunk as chunk_fn
    elif strat == "integrated_email":
        from app.third_party.integrated_pipeline.chunkers.email import chunk as chunk_fn
    else:
        raise ValueError(
            f"Unsupported Integrated pipeline strategy: {strategy}. "
            f"Supported: integrated_naive, integrated_book, integrated_laws, integrated_email"
        )

    if callback is None:
        def callback(prog=None, msg=""):
            if msg:
                logger.info("[integrated] %s (%s)", msg, prog)

    return chunk_fn(str(file_path), binary=binary, callback=callback, **kwargs)
