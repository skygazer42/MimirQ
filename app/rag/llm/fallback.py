from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.rag.core.logging import get_logger
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMResponse

logger = get_logger("rag.llm.fallback")

_RETRYABLE_EXCEPTIONS = (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError)


class AllProvidersFailedError(RuntimeError):
    """Raised when all configured fallback providers fail with retryable errors."""


class FallbackLLMClient(BaseLLMClient):
    """Wrapper that retries LLM calls across a provider chain."""

    def __init__(self, clients: list[BaseLLMClient]) -> None:
        if not clients:
            raise ValueError("FallbackLLMClient requires at least one client")
        self._clients = list(clients)

    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> LLMResponse:
        last_exc: Exception | None = None
        for idx, client in enumerate(self._clients):
            try:
                return await client.chat(messages, temperature=temperature, max_tokens=max_tokens, **kwargs)
            except _RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                logger.warning(
                    "LLM provider %d/%d failed with retryable error: %s",
                    idx + 1,
                    len(self._clients),
                    str(exc)[:200],
                )
                continue
        if last_exc is not None:
            raise AllProvidersFailedError("all LLM providers failed") from last_exc
        raise AllProvidersFailedError("all LLM providers failed")

    def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        include_reasoning: bool = False,
        **kwargs: object,
    ) -> AsyncIterator[tuple[str, str | None]]:
        async def _gen() -> AsyncIterator[tuple[str, str | None]]:
            last_exc: Exception | None = None
            for idx, client in enumerate(self._clients):
                try:
                    async for chunk in client.chat_stream(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        include_reasoning=include_reasoning,
                        **kwargs,
                    ):
                        yield chunk
                    return
                except _RETRYABLE_EXCEPTIONS as exc:
                    last_exc = exc
                    logger.warning(
                        "LLM stream provider %d/%d failed with retryable error: %s",
                        idx + 1,
                        len(self._clients),
                        str(exc)[:200],
                    )
                    continue
            if last_exc is not None:
                raise AllProvidersFailedError("all LLM stream providers failed") from last_exc
            raise AllProvidersFailedError("all LLM stream providers failed")

        return _gen()


__all__ = ["FallbackLLMClient", "AllProvidersFailedError"]
