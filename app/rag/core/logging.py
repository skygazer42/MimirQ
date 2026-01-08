"""
Logging helpers for the RAG package.
"""


import logging
from typing import Optional


def setup_logging(level: int = logging.INFO) -> None:
    """Initialize basic logging once."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a configured logger."""
    return logging.getLogger(name or "rag")

