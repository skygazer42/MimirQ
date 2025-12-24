"""
SAG utilities and exceptions.
Merged from sag/utils.py and sag/exceptions.py
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
    return logging.getLogger(name or "sag")


def estimate_tokens(text: str) -> int:
    """Rough token estimate used for guards; not exact."""
    return max(1, len(text) // 4)


# === Exceptions ===


class ExtractError(Exception):
    """Extraction failure."""


class SearchError(Exception):
    """Search failure."""


class AIError(Exception):
    """Generic AI/LLM error."""


class ConfigError(Exception):
    """Configuration missing or invalid."""


class LLMError(Exception):
    """LLM runtime error."""


class LLMTimeoutError(LLMError):
    """LLM timeout."""


class LoadError(Exception):
    """Document load failure."""


class PromptError(Exception):
    """Prompt template error."""
