"""
KG utilities and exceptions.

Note:
Historically this module was used as a shared place for logging and common
exception types. As `kg` is now treated as a plugin under the `rag` package,
the canonical definitions live in `app.rag.core`.

This file remains as a compatibility layer for existing imports.
"""

from __future__ import annotations

from app.rag.core import (
    AIError,
    ConfigError,
    ExtractError,
    LLMError,
    LLMTimeoutError,
    LoadError,
    PromptError,
    SearchError,
    estimate_tokens,
    get_logger,
    setup_logging,
)

__all__ = [
    "setup_logging",
    "get_logger",
    "estimate_tokens",
    "ExtractError",
    "SearchError",
    "AIError",
    "ConfigError",
    "LLMError",
    "LLMTimeoutError",
    "LoadError",
    "PromptError",
]
