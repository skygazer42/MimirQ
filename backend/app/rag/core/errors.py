"""
Shared error types used across RAG pipelines and plugins.

These exceptions are intentionally lightweight and should not import heavy
dependencies to avoid circular imports.
"""


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

