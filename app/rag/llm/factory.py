"""
Select and assemble chat clients from the existing project settings.
"""

import asyncio
import json
import logging
from typing import Any

import httpx

from app.infrastructure.config import settings
from app.infrastructure.runtime.async_bridge import run_blocking_in_thread
from app.rag.llm.base import BaseLLMClient, _await_llm_close
from app.rag.llm.client import OpenAIChatClient
from app.rag.llm.fallback import FallbackLLMClient, _close_llm_clients
from app.types.document_metadata import metadata_text

logger = logging.getLogger("rag.llm.factory")


def _normalize_fallback_spec(spec: object) -> dict[str, Any] | None:
    if isinstance(spec, dict):
        out = {str(k): v for k, v in spec.items()}
        model_name = metadata_text(out, "model")
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
    text = raw.strip()
    if not text:
        return []
    if text.startswith(("{", "[")):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in LLM_FALLBACK_MODELS; ignoring")
            return []
        items = parsed if isinstance(parsed, list) else [parsed]
    else:
        items = text.split(",")

    out: list[dict[str, Any]] = []
    for item in items:
        normalized = _normalize_fallback_spec(item)
        if normalized is not None:
            out.append(normalized)
    return out


def _resolve_fallback_specs(*, base_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    parsed = _parse_fallback_specs(settings.LLM_FALLBACK_MODELS)
    if not parsed:
        return []
    base = dict(base_config or {})
    inherited_keys = ("api_key", "base_url", "temperature", "timeout", "max_retries")
    inherited = {key: base[key] for key in inherited_keys if key in base}
    resolved: list[dict[str, Any]] = []
    for spec in parsed:
        merged = dict(spec)
        for key, value in inherited.items():
            merged.setdefault(key, value)
        resolved.append(merged)
    return resolved


def _llm_ctor_kwargs(
    *,
    model_config: dict[str, Any] | None,
    http_client: httpx.Client | None,
    http_async_client: httpx.AsyncClient | None,
) -> dict[str, Any]:
    ctor_kwargs: dict[str, Any] = {"model_config": model_config}
    if http_client is not None:
        ctor_kwargs["http_client"] = http_client
    if http_async_client is not None:
        ctor_kwargs["http_async_client"] = http_async_client
    return ctor_kwargs


async def _build_fallback_clients(
    *,
    clients: list[BaseLLMClient],
    model_config: dict[str, Any] | None,
    http_client: httpx.Client | None,
    http_async_client: httpx.AsyncClient | None,
) -> None:
    specs = _resolve_fallback_specs(base_config=model_config)
    if not specs:
        return

    primary_model = str((model_config or {}).get("model") or settings.LLM_MODEL).strip()
    seen_models = {primary_model} if primary_model else set()
    for spec in specs:
        model_name = spec["model"]
        if model_name in seen_models:
            continue
        try:
            fallback_client = await _construct_llm_client(
                ctor_kwargs=_llm_ctor_kwargs(
                    model_config=spec,
                    http_client=http_client,
                    http_async_client=http_async_client,
                ),
            )
        except Exception as exc:
            logger.warning("Failed to initialize fallback LLM model '%s': %s", model_name, str(exc)[:200])
            continue
        clients.append(fallback_client)
        seen_models.add(model_name)


async def _construct_llm_client(*, ctor_kwargs: dict[str, Any]) -> BaseLLMClient:
    created: BaseLLMClient | None = None

    def construct() -> BaseLLMClient:
        nonlocal created
        created = OpenAIChatClient(**ctor_kwargs)
        return created

    def log_cancelled_error(error: BaseException) -> None:
        logger.warning("LLM construction failed during cancellation: %s", type(error).__name__)

    try:
        return await run_blocking_in_thread(construct, on_cancelled_worker_error=log_cancelled_error)
    except BaseException:
        if created is not None:
            await _await_llm_close(asyncio.create_task(created.aclose()))
        raise


async def create_llm_client(
    model_config: dict[str, Any] | None = None,
    *,
    http_client: httpx.Client | None = None,
    http_async_client: httpx.AsyncClient | None = None,
) -> BaseLLMClient:
    primary = await _construct_llm_client(
        ctor_kwargs=_llm_ctor_kwargs(
            model_config=model_config,
            http_client=http_client,
            http_async_client=http_async_client,
        ),
    )

    clients = [primary]
    try:
        if not settings.LLM_FALLBACK_ENABLED:
            return primary
        await _build_fallback_clients(
            clients=clients,
            model_config=model_config,
            http_client=http_client,
            http_async_client=http_async_client,
        )
        if len(clients) <= 1:
            return primary
        return FallbackLLMClient(clients)
    except BaseException:
        await _await_llm_close(asyncio.create_task(_close_llm_clients(clients)))
        raise


__all__ = ["create_llm_client", "_parse_fallback_specs"]
