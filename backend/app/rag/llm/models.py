from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional


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
    usage: Optional[dict] = None
