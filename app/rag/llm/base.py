from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.rag.core.code_fence import extract_first_code_fence
from app.rag.core.logging import get_logger
from app.rag.llm.models import LLMMessage, LLMResponse, LLMRole

logger = get_logger("rag.llm.base")


class BaseLLMClient(ABC):
    """Abstract LLM client used by RAG/KG algorithms."""

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        ...

    @abstractmethod
    def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        include_reasoning: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[str, str | None]]:
        ...

    async def chat_with_schema(
        self,
        messages: list[LLMMessage],
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Ask the LLM to return JSON and parse it. If schema is provided,
        it is appended as a system message hint (no strict validation).
        """
        import json

        enhanced_messages: list[LLMMessage] = []
        if response_schema:
            schema_prompt = (
                "Return JSON that follows the schema. If a field is missing, use null.\n"
                f"{json.dumps(response_schema, ensure_ascii=False)}"
            )
            enhanced_messages.append(LLMMessage(role=LLMRole.SYSTEM, content=schema_prompt))
        enhanced_messages.extend(messages)

        response = await self.chat(
            enhanced_messages, temperature=temperature, max_tokens=max_tokens, **kwargs
        )

        content = response.content.strip()
        fenced = extract_first_code_fence(content, allowed_info_strings={"", "json"})
        if fenced is not None:
            content = fenced

        try:
            return json.loads(content)
        except Exception as exc:
            logger.warning("Failed to parse JSON from LLM, returning raw text: %s", exc)
            return {"raw": content}


__all__ = ["BaseLLMClient"]
