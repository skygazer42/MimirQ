import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing

import httpx
import openai

from app.rag.llm.base import BaseLLMClient, _await_llm_close
from app.rag.llm.models import LLMMessage, LLMResponse

logger = logging.getLogger("rag.llm.fallback")


async def _close_llm_clients(clients: list[BaseLLMClient]) -> None:
    errors: list[BaseException] = []
    for client in clients:
        try:
            await client.aclose()
        except BaseException as exc:
            errors.append(exc)
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup("LLM provider cleanup failed", errors)


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
        status_code = exc.response.status_code
    elif isinstance(exc, openai.APIStatusError):
        status_code = exc.status_code
    else:
        return False
    return status_code >= 500 or status_code == 429


class FallbackLLMClient(BaseLLMClient):
    """Wrapper that retries LLM calls across a provider chain."""

    def __init__(self, clients: list[BaseLLMClient]) -> None:
        if not clients:
            raise ValueError("FallbackLLMClient requires at least one client")
        self._clients = list(clients)
        self._close_task: asyncio.Task[None] | None = None

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(_close_llm_clients(self._clients))
        await _await_llm_close(self._close_task)

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
        raise AllProvidersFailedError("all LLM providers failed") from last_exc

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
                    async with aclosing(
                        client.chat_stream(
                            messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            include_reasoning=include_reasoning,
                            **kwargs,
                        )
                    ) as stream:
                        async for chunk in stream:
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
            raise AllProvidersFailedError("all LLM stream providers failed") from last_exc

        return _gen()


__all__ = ["FallbackLLMClient", "AllProvidersFailedError", "is_retryable_provider_error"]
