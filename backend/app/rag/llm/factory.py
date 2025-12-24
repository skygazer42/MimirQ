"""
Factory for LLM and embedding clients backed by the existing project settings.
"""
import os
from typing import Any, Dict, Optional

import httpx
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import settings
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMResponse, LLMRole
from app.core.sag_utils import ConfigError, get_logger
from app.storage.vector.milvus import milvus_store

logger = get_logger("sag.ai.factory")


class OpenAIChatClient(BaseLLMClient):
    """Thin wrapper around langchain_openai.ChatOpenAI to match SAG's BaseLLMClient."""

    def __init__(self, model_config: Optional[Dict[str, Any]] = None) -> None:
        proxy_candidates = [
            os.getenv("HTTPS_PROXY"),
            os.getenv("HTTP_PROXY"),
            os.getenv("ALL_PROXY"),
            os.getenv("https_proxy"),
            os.getenv("http_proxy"),
            os.getenv("all_proxy"),
        ]
        proxies = [p for p in proxy_candidates if p]
        trust_env = True
        socks_proxy = next((p for p in proxies if p and p.lower().startswith("socks")), None)
        if socks_proxy:
            logger.warning("Ignoring SOCKS proxy for LLM: %s", socks_proxy)
            trust_env = False

        cfg = model_config or {}
        model_name = cfg.get("model") or settings.LLM_MODEL
        api_key = cfg.get("api_key") or settings.LLM_API_KEY
        base_url = cfg.get("base_url") or settings.LLM_API_BASE
        temperature = cfg.get("temperature", settings.LLM_TEMPERATURE)
        timeout = cfg.get("timeout", settings.LLM_TIMEOUT)
        max_retries = cfg.get("max_retries", settings.LLM_MAX_RETRIES)

        if not api_key or not model_name:
            raise ConfigError("LLM configuration missing api_key or model")

        http_client = httpx.Client(trust_env=trust_env, timeout=timeout)
        self._client = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            streaming=False,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

    def _convert_messages(self, messages: list[LLMMessage]):
        converted = []
        for msg in messages:
            if msg.role == LLMRole.SYSTEM:
                converted.append(SystemMessage(content=msg.content))
            elif msg.role == LLMRole.ASSISTANT:
                converted.append(AIMessage(content=msg.content))
            else:
                converted.append(HumanMessage(content=msg.content))
        return converted

    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        converted = self._convert_messages(messages)
        resp = await self._client.ainvoke(
            converted,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return LLMResponse(content=resp.content, raw=resp)

    def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        include_reasoning: bool = False,
        **kwargs: Any,
    ):
        # Streaming not required for SAG algorithms in this integration.
        async def _gen():
            resp = await self.chat(messages, temperature=temperature, max_tokens=max_tokens, **kwargs)
            yield resp.content, None

        return _gen()


class EmbeddingClient:
    """Adapter to reuse the project's embedding provider."""

    def __init__(self):
        # Reuse Milvus embedding configuration to avoid duplication.
        self._provider = milvus_store._init_embedding_model()  # noqa: SLF001

    async def generate(self, text: str) -> list[float]:
        if hasattr(self._provider, "embed_query"):
            return self._provider.embed_query(text)  # type: ignore[attr-defined]
        if hasattr(self._provider, "embed_documents"):
            return self._provider.embed_documents([text])[0]  # type: ignore[attr-defined]
        raise RuntimeError("Embedding provider missing embed_query/embed_documents")

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        if hasattr(self._provider, "embed_documents"):
            return self._provider.embed_documents(texts)  # type: ignore[attr-defined]
        # Fallback: loop
        return [await self.generate(t) for t in texts]


async def create_llm_client(
    scenario: str = "general",
    model_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> BaseLLMClient:
    _ = scenario  # reserved for future branching
    return OpenAIChatClient(model_config=model_config)


async def get_embedding_client(
    scenario: str = "general",
    **kwargs: Any,
) -> EmbeddingClient:
    _ = scenario
    return EmbeddingClient()
