import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from math import isfinite
from typing import Any

from app.infrastructure.runtime.async_bridge import _wait_for_worker_after_cancellation
from app.rag.llm.models import LLMMessage, LLMResponse, LLMRole
from app.rag.llm.response_parsing import extract_first_code_fence

_ASYNC_CLEANUP_TIMEOUT_SEC = 5.0


async def _await_llm_close(task: asyncio.Task[None]) -> None:
    """Finish owned cleanup on its loop before propagating caller cancellation."""
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError as cancelled:
        error = await _wait_for_worker_after_cancellation(task)
        if error is not None:
            raise error from cancelled
        raise


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"LLM JSON response contains a non-finite number: {value}")


def _parse_finite_json_float(value: str) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError("LLM JSON response number exceeds the finite float range")
    return number


class BaseLLMClient(ABC):
    """Abstract LLM client used by RAG/KG algorithms."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close resources owned by this client; borrowed transports remain open."""
        ...

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse: ...

    @abstractmethod
    def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        include_reasoning: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[str, str | None]]: ...

    async def chat_with_schema(
        self,
        messages: list[LLMMessage],
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Parse a JSON object. A supplied schema is a prompt hint; domain fields
        remain the caller's validation responsibility. Malformed output raises.
        """
        import json

        enhanced_messages: list[LLMMessage] = []
        if response_schema:
            schema_prompt = (
                "Return JSON that follows the schema. Omit optional fields you cannot fill. "
                "Null is valid only when the field schema permits it.\n"
                f"{json.dumps(response_schema, ensure_ascii=False, separators=(',', ':'))}"
            )
            enhanced_messages.append(LLMMessage(role=LLMRole.SYSTEM, content=schema_prompt))
        enhanced_messages.extend(messages)

        response = await self.chat(enhanced_messages, temperature=temperature, max_tokens=max_tokens, **kwargs)

        content = response.content.strip()
        fenced = extract_first_code_fence(content, allowed_info_strings={"", "json"})
        if fenced is not None:
            content = fenced

        parsed = json.loads(content, parse_constant=_reject_nonfinite_json, parse_float=_parse_finite_json_float)
        if not isinstance(parsed, dict):
            raise ValueError("LLM JSON response must be an object")
        return parsed


__all__ = ["BaseLLMClient"]
