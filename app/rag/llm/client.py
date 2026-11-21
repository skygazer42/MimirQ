"""OpenAI-compatible chat client and HTTP transport configuration."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

import anyio
import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.infrastructure.config import settings
from app.infrastructure.exceptions import ConfigError
from app.infrastructure.http.environment import httpx_trust_env
from app.infrastructure.http.openai import normalize_openai_compatible_base_url
from app.infrastructure.runtime.async_bridge import run_blocking_in_thread, run_coroutine_sync
from app.rag.llm.base import _ASYNC_CLEANUP_TIMEOUT_SEC, BaseLLMClient, _await_llm_close
from app.rag.llm.models import LLMMessage, LLMResponse, LLMRole
from app.rag.llm.prompt_cache import annotate_prompt_cache_content, detect_anthropic_compatible, message_content_to_text

logger = logging.getLogger("rag.llm.factory")
_MESSAGE_TYPES = {LLMRole.SYSTEM: SystemMessage, LLMRole.ASSISTANT: AIMessage}


def _resolve_explicit_http_proxy() -> str | None:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.getenv(key)
        if value is not None:
            value = value.strip()
        if value and not value.lower().startswith("socks"):
            return value
    return None


class OpenAIChatClient(BaseLLMClient):
    """Thin wrapper around langchain_openai.ChatOpenAI to match BaseLLMClient."""

    def __init__(
        self,
        model_config: dict[str, Any] | None = None,
        *,
        http_client: httpx.Client | None = None,
        http_async_client: httpx.AsyncClient | None = None,
    ) -> None:
        trust_env = httpx_trust_env(logger=logger)

        cfg = model_config or {}
        model_name = cfg.get("model") or settings.LLM_MODEL
        api_key = cfg.get("api_key") or settings.LLM_API_KEY
        base_url = normalize_openai_compatible_base_url(cfg.get("base_url") or settings.LLM_API_BASE)
        temperature = cfg.get("temperature", settings.LLM_TEMPERATURE)
        timeout = cfg.get("timeout", settings.LLM_TIMEOUT)
        max_retries = cfg.get("max_retries", settings.LLM_MAX_RETRIES)

        if not api_key or not model_name:
            raise ConfigError("LLM configuration missing api_key or model")

        self.model_name = str(model_name)
        self._is_anthropic_compatible = detect_anthropic_compatible(
            model_name=str(model_name),
            base_url=str(base_url),
        )

        self._owned_http_client: httpx.Client | None = None
        self._owned_http_async_client: httpx.AsyncClient | None = None
        self._close_task: asyncio.Task[None] | None = None
        explicit_proxy = _resolve_explicit_http_proxy() if not trust_env else None
        client_trust_env = trust_env if explicit_proxy is None else False
        try:
            if http_client is None:
                http_client = httpx.Client(trust_env=client_trust_env, timeout=timeout, proxy=explicit_proxy)
                self._owned_http_client = http_client
            if http_async_client is None:
                http_async_client = httpx.AsyncClient(trust_env=client_trust_env, timeout=timeout, proxy=explicit_proxy)
                self._owned_http_async_client = http_async_client
            # Default clients remain dedicated. Explicitly injected clients are
            # borrowed and must be used regardless of the shared-pool preference.
            self._client = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=temperature,
                streaming=False,
                timeout=timeout,
                max_retries=max_retries,
                http_client=http_client,
                http_async_client=http_async_client,
            )
        except BaseException:
            # Fresh transports have not performed I/O or become loop-bound yet.
            run_coroutine_sync(self.aclose)
            raise

    async def _close_owned_transports(self) -> None:
        errors: list[BaseException] = []
        if self._owned_http_async_client is not None:
            try:
                with anyio.fail_after(_ASYNC_CLEANUP_TIMEOUT_SEC, shield=True):
                    await self._owned_http_async_client.aclose()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._owned_http_async_client = None
        if self._owned_http_client is not None:
            try:
                await run_blocking_in_thread(self._owned_http_client.close)
            except BaseException as exc:
                errors.append(exc)
            else:
                self._owned_http_client = None
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("LLM transport cleanup failed", errors)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_owned_transports())
        await _await_llm_close(self._close_task)

    def _convert_messages(self, messages: list[LLMMessage]) -> list[BaseMessage]:
        converted: list[BaseMessage] = []
        for msg in messages:
            content, _ = annotate_prompt_cache_content(
                role=str(msg.role),
                content=msg.content,
                anthropic_compatible=self._is_anthropic_compatible,
            )
            message_type = _MESSAGE_TYPES.get(msg.role, HumanMessage)
            converted.append(message_type(content=content))
        return converted

    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        converted = self._convert_messages(messages)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        resp = await self._client.ainvoke(
            converted,
            **kwargs,
        )
        return LLMResponse(content=message_content_to_text(resp.content), raw=resp)

    def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        include_reasoning: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[str, str | None]]:
        _ = include_reasoning
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        async def _gen() -> AsyncIterator[tuple[str, str | None]]:
            converted = self._convert_messages(messages)
            async with aclosing(self._client.astream(converted, **kwargs)) as stream:
                async for chunk in stream:
                    text = message_content_to_text(chunk.content)
                    if text:
                        yield text, None

        return _gen()
