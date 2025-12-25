"""
DEPRECATED: legacy import path for SAG/KG LLM models.

Canonical implementation moved to `app.ai.models`.
"""

from app.ai.models import LLMMessage, LLMResponse, LLMRole  # noqa: F401

__all__ = ["LLMMessage", "LLMResponse", "LLMRole"]
