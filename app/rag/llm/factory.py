"""
Factory for LLM and embedding clients backed by the existing project settings.
"""
import asyncio
import json
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.rag.core.errors import ConfigError
from app.rag.core.http import httpx_trust_env
from app.rag.core.logging import get_logger
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.fallback import FallbackLLMClient
from app.rag.llm.models import LLMMessage, LLMResponse, LLMRole
from app.rag.llm.prompt_cache import annotate_prompt_cache_content, detect_anthropic_compatible
from app.storage.vector.milvus import milvus_store

logger = get_logger("rag.llm.factory")


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").strip().lower() != "text":
                continue
            parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return str(content or "")


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

        if http_client is None:
            http_client = httpx.Client(trust_env=trust_env, timeout=timeout)
        if http_async_client is None:
            http_async_client = httpx.AsyncClient(trust_env=trust_env, timeout=timeout)
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

    def _should_cache_message(self, msg: LLMMessage) -> bool:
        _content, applied = annotate_prompt_cache_content(
            role=str(msg.role or ""),
            content=msg.content,
            anthropic_compatible=bool(self._is_anthropic_compatible),
        )
        return bool(applied)

    def _convert_messages(self, messages: list[LLMMessage]):
        converted = []
        cached_count = 0
        for msg in messages:
            content, applied = annotate_prompt_cache_content(
                role=str(msg.role or ""),
                content=msg.content,
                anthropic_compatible=bool(self._is_anthropic_compatible),
            )
            if applied:
                cached_count += 1
            if msg.role == LLMRole.SYSTEM:
                converted.append(SystemMessage(content=content))
            elif msg.role == LLMRole.ASSISTANT:
                converted.append(AIMessage(content=content))
            else:
                converted.append(HumanMessage(content=content))
        self._last_invocation_meta = {
            "selected_model": getattr(self, "model_name", None),
            "prompt_cache_applied": bool(cached_count),
            "prompt_cache_message_count": int(cached_count),
            "provider_anthropic_compatible": bool(self._is_anthropic_compatible),
        }
        return converted

    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        converted = self._convert_messages(messages)
        resp = await self._client.ainvoke(
            converted,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return LLMResponse(content=_message_content_to_text(resp.content), raw=resp)

    def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        include_reasoning: bool = False,
        **kwargs: Any,
    ):
        _ = include_reasoning

        async def _gen():
            converted = self._convert_messages(messages)
            async for chunk in self._client.astream(
                converted,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            ):
                text = _message_content_to_text(getattr(chunk, "content", ""))
                if text:
                    yield text, None

        return _gen()


class EmbeddingClient:
    """Adapter to reuse the project's embedding provider."""

    def __init__(self):
        self._provider = milvus_store._init_embedding_model()  # noqa: SLF001

    async def generate(self, text: str) -> list[float]:
        provider = self._provider
        if hasattr(provider, "embed_query"):
            return await asyncio.to_thread(provider.embed_query, text)  # type: ignore[attr-defined]
        if hasattr(provider, "embed_documents"):
            out = await asyncio.to_thread(provider.embed_documents, [text])  # type: ignore[attr-defined]
            return out[0] if out else []
        raise RuntimeError("Embedding provider missing embed_query/embed_documents")

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        provider = self._provider
        if hasattr(provider, "embed_documents"):
            return await asyncio.to_thread(provider.embed_documents, texts)  # type: ignore[attr-defined]
        return [await self.generate(t) for t in texts]


def _normalize_fallback_spec(spec: object) -> dict[str, Any] | None:
    if isinstance(spec, dict):
        out = {str(k): v for k, v in spec.items()}
        model_name = str(out.get("model") or "").strip()
        if not model_name:
            return None
        out["model"] = model_name
        return out
    if isinstance(spec, str):
        model_name = spec.strip()
        if model_name:
            return {"model": model_name}
    return None


def _parse_fallback_specs(raw: str) -> list[dict[str, Any]]:
    text = str(raw or "").strip()
    if not text:
        return []
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in LLM_FALLBACK_MODELS; ignoring")
            return []
        if isinstance(parsed, dict):
            one = _normalize_fallback_spec(parsed)
            return [one] if one else []
        if isinstance(parsed, list):
            out: list[dict[str, Any]] = []
            for item in parsed:
                normalized = _normalize_fallback_spec(item)
                if normalized is not None:
                    out.append(normalized)
            return out
        return []

    out: list[dict[str, Any]] = []
    for part in text.split(","):
        normalized = _normalize_fallback_spec(part)
        if normalized is not None:
            out.append(normalized)
    return out


def _resolve_fallback_specs(*, base_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw = str(getattr(settings, "LLM_FALLBACK_MODELS", "") or "").strip()
    parsed = _parse_fallback_specs(raw)
    if not parsed:
        return []
    base = dict(base_config or {})
    inherited_keys = ("api_key", "base_url", "temperature", "timeout", "max_retries")
    resolved: list[dict[str, Any]] = []
    for spec in parsed:
        merged = dict(spec)
        for key in inherited_keys:
            if key not in merged and key in base:
                merged[key] = base[key]
        resolved.append(merged)
    return resolved


async def create_llm_client(
    scenario: str = "general",
    model_config: dict[str, Any] | None = None,
    **kwargs: Any,
) -> BaseLLMClient:
    _ = scenario
    _ = kwargs
    http_client = kwargs.get("http_client")
    http_async_client = kwargs.get("http_async_client")
    ctor_kwargs: dict[str, Any] = {"model_config": model_config}
    if http_client is not None:
        ctor_kwargs["http_client"] = http_client
    if http_async_client is not None:
        ctor_kwargs["http_async_client"] = http_async_client
    primary = await asyncio.to_thread(OpenAIChatClient, **ctor_kwargs)

    if not bool(getattr(settings, "LLM_FALLBACK_ENABLED", False)):
        return primary

    specs = _resolve_fallback_specs(base_config=model_config)
    if not specs:
        return primary

    primary_model = str((model_config or {}).get("model") or settings.LLM_MODEL or "").strip()
    clients: list[BaseLLMClient] = [primary]
    seen_models = {primary_model} if primary_model else set()
    for spec in specs:
        model_name = str(spec.get("model") or "").strip()
        if not model_name or model_name in seen_models:
            continue
        try:
            fallback_ctor_kwargs: dict[str, Any] = {"model_config": spec}
            if http_client is not None:
                fallback_ctor_kwargs["http_client"] = http_client
            if http_async_client is not None:
                fallback_ctor_kwargs["http_async_client"] = http_async_client
            fallback_client = await asyncio.to_thread(OpenAIChatClient, **fallback_ctor_kwargs)
            clients.append(fallback_client)
            seen_models.add(model_name)
        except Exception as exc:
            logger.warning("Failed to initialize fallback LLM model '%s': %s", model_name, str(exc)[:200])

    if len(clients) <= 1:
        return primary
    return FallbackLLMClient(clients)


async def get_embedding_client(
    scenario: str = "general",
    **kwargs: Any,
) -> EmbeddingClient:
    _ = scenario
    _ = kwargs
    return await asyncio.to_thread(EmbeddingClient)


__all__ = [
    "OpenAIChatClient",
    "EmbeddingClient",
    "create_llm_client",
    "get_embedding_client",
    "_parse_fallback_specs",
]
