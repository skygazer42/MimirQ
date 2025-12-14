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
    return logging.getLogger(name or "sag")


def estimate_tokens(text: str) -> int:
    """Rough token estimate used for guards; not exact."""
    return max(1, len(text) // 4)

