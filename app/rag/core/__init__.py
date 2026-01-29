"""
RAG core utilities (shared, dependency-light).

This package hosts the minimal shared building blocks that both the main RAG
pipelines and optional plugins (e.g. KG) can reuse without creating circular
imports:
- logging helpers
- shared exception types
- small text/token utilities
- Command objects for workflow control
"""

from app.rag.core.command import (
    Command,
    CommandProcessor,
    Interrupt,
    NodeReturn,
    Send,
    interrupt,
)
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
    # Command objects
    "Command",
    "Send",
    "Interrupt",
    "interrupt",
    "CommandProcessor",
    "NodeReturn",
]

