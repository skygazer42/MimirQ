from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import openai

from app.rag.core.logging import get_logger
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMResponse

logger = get_logger("rag.llm.fallback")


class AllProvidersFailedError(RuntimeError):
    """Raised when all configured fallback providers fail with retryable errors."""


def is_retryable_provider_error(exc: Exception) -> bool:
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.TimeoutException,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.RateLimitError,
        ),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    if isinstance(exc, openai.APIStatusError):
        status_code = int(getattr(exc, "status_code", 0) or 0)
        return status_code >= 500 or status_code == 429
    return False


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
            except Exception as exc:  # noqa: BLE001
                if not is_retryable_provider_error(exc):
                    raise
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
                yielded_any = False
                try:
                    async for chunk in client.chat_stream(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        include_reasoning=include_reasoning,
                        **kwargs,
                    ):
                        yielded_any = True
                        yield chunk
                    return
                except Exception as exc:  # noqa: BLE001
                    if yielded_any:
                        raise
                    if not is_retryable_provider_error(exc):
                        raise
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


__all__ = ["FallbackLLMClient", "AllProvidersFailedError", "is_retryable_provider_error"]
