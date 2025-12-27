"""
RAG core utilities (shared, dependency-light).

This package hosts the minimal shared building blocks that both the main RAG
pipelines and optional plugins (e.g. KG) can reuse without creating circular
imports:
- logging helpers
- shared exception types
- small text/token utilities
"""

from app.rag.core.errors import (
    AIError,
    ConfigError,
    ExtractError,
    LLMError,
    LLMTimeoutError,
    LoadError,
    PromptError,
    SearchError,
)
from app.rag.core.logging import get_logger, setup_logging
from app.rag.core.text import estimate_tokens

__all__ = [
    "get_logger",
    "setup_logging",
    "estimate_tokens",
    "AIError",
    "ConfigError",
    "ExtractError",
    "LLMError",
    "LLMTimeoutError",
    "LoadError",
    "PromptError",
    "SearchError",
]

