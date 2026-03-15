"""
Core LLM data models used by RAG and KG pipelines.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class LLMRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"

    def __str__(self) -> str:
        return self.value


@dataclass
class LLMMessage:
    role: LLMRole
    content: str


@dataclass
class LLMResponse:
    content: str
    raw: Any = None
    usage: dict | None = None


__all__ = ["LLMMessage", "LLMResponse", "LLMRole"]
