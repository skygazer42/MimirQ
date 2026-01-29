"""
Shared error types used across RAG pipelines and plugins.

Re-exports from app.core.exceptions to maintain backward compatibility.
All exceptions are now centralized in app/core/exceptions.py.
"""

from app.core.exceptions import (
    AIError,
    ConfigError,
    ExtractError,
    LLMError,
    LLMTimeoutError,
    LoadError,
    PromptError,
    SearchError,
)

__all__ = [
    "ExtractError",
    "SearchError",
    "AIError",
    "ConfigError",
    "LLMError",
    "LLMTimeoutError",
    "LoadError",
    "PromptError",
]
