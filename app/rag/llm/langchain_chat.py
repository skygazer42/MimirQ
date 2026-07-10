
import contextvars
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import ConfigDict, Field, PrivateAttr

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.rag.core.http import httpx_trust_env
from app.rag.core.logging import get_logger
from app.rag.llm.factory import _resolve_fallback_specs
from app.rag.llm.fallback import AllProvidersFailedError, is_retryable_provider_error
from app.rag.llm.prompt_cache import (
    annotate_openai_messages_for_prompt_cache,
    detect_anthropic_compatible,
)

logger = get_logger("rag.llm.langchain_chat")


def _model_name_of(model: Any) -> str | None:
    for attr in ("model_name", "model"):
        value = getattr(model, attr, None)
        if value:
            return str(value)
    return None


def _prompt_cache_meta(model: Any) -> dict[str, Any]:
    getter = getattr(model, "get_last_payload_meta", None)
    if callable(getter):
        try:
            meta = getter()
        except Exception:  # noqa: BLE001
            return {}
        return dict(meta or {})
    return {}


class PromptCacheChatOpenAI(ChatOpenAI):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    _anthropic_compatible: bool = PrivateAttr(default=False)
    _payload_meta_var: contextvars.ContextVar[dict[str, Any] | None] = PrivateAttr(
        default_factory=lambda: contextvars.ContextVar("prompt_cache_chat_openai_meta", default=None)
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        base_url = normalize_openai_compatible_base_url(kwargs.get("base_url"))
        super().__init__(*args, **kwargs)
        self._anthropic_compatible = detect_anthropic_compatible(
            model_name=str(getattr(self, "model_name", "") or ""),
            base_url=str(base_url or ""),
        )

    def get_last_payload_meta(self) -> dict[str, Any]:
        return dict(self._payload_meta_var.get() or {})

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            self._payload_meta_var.set(
                {
                    "prompt_cache_applied": False,
                    "prompt_cache_message_count": 0,
                    "provider_anthropic_compatible": bool(self._anthropic_compatible),
                }
            )
            return payload

        annotated, meta = annotate_openai_messages_for_prompt_cache(
            messages=list(raw_messages),
            anthropic_compatible=self._anthropic_compatible,
        )
        payload["messages"] = annotated
        self._payload_meta_var.set(meta)
        return payload


class FallbackChatOpenAI(BaseChatModel):
    primary: BaseChatModel
    fallbacks: list[BaseChatModel] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _invocation_meta_var: contextvars.ContextVar[dict[str, Any] | None] = PrivateAttr(
        default_factory=lambda: contextvars.ContextVar("fallback_chat_openai_meta", default=None)
    )
    _last_invocation_meta: dict[str, Any] | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "fallback_chat_openai"

    @property
    def model_name(self) -> str | None:
        meta = self.get_last_invocation_meta()
        return str(meta.get("selected_model") or _model_name_of(self.primary) or "") or None

    @property
    def model(self) -> str | None:
        return self.model_name

    def get_last_invocation_meta(self) -> dict[str, Any]:
        meta = self._invocation_meta_var.get()
        if meta is None:
            meta = self._last_invocation_meta
        return dict(meta or {})

    def _models(self) -> list[BaseChatModel]:
        return [self.primary, *list(self.fallbacks)]

    def _attempt_entry(
        self,
        *,
        model: BaseChatModel,
        success: bool,
        error: Exception | None = None,
        yielded_tokens: bool = False,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "model": _model_name_of(model),
            "success": bool(success),
            "yielded_tokens": bool(yielded_tokens),
        }
        if error is not None:
            entry["error_type"] = error.__class__.__name__
            entry["error"] = str(error)[:200]
        return entry

    def _final_meta(
        self,
        *,
        attempts: list[dict[str, Any]],
        selected_model: str | None,
        prompt_cache: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cache = dict(prompt_cache or {})
        failure_count = sum(1 for attempt in attempts if not bool(attempt.get("success")))
        return {
            "attempts": attempts,
            "failure_count": int(failure_count),
            "fallback_used": bool(selected_model and attempts and attempts[0].get("model") != selected_model),
            "selected_model": selected_model,
            "prompt_cache_applied": bool(cache.get("prompt_cache_applied")),
            "prompt_cache_message_count": int(cache.get("prompt_cache_message_count") or 0),
            "provider_anthropic_compatible": bool(cache.get("provider_anthropic_compatible")),
        }

    def _raise_all_failed(self, last_exc: Exception | None) -> None:
        if last_exc is not None:
            raise AllProvidersFailedError("all LLM providers failed") from last_exc
        raise AllProvidersFailedError("all LLM providers failed")

    def _record_attempt(
        self,
        attempts: list[dict[str, Any]],
        *,
        model: BaseChatModel,
        success: bool,
        error: Exception | None = None,
        yielded_tokens: bool | None = None,
    ) -> None:
        attempts.append(
            self._attempt_entry(model=model, success=success, error=error, yielded_tokens=yielded_tokens)
        )

    def _set_success_metadata(
        self,
        attempts: list[dict[str, Any]],
        *,
        model: BaseChatModel,
        yielded_tokens: bool | None = None,
    ) -> None:
        prompt_cache = _prompt_cache_meta(model)
        selected_model = _model_name_of(model)
        self._record_attempt(attempts, model=model, success=True, yielded_tokens=yielded_tokens)
        meta = self._final_meta(
            attempts=attempts,
            selected_model=selected_model,
            prompt_cache=prompt_cache,
        )
        self._invocation_meta_var.set(meta)
        self._last_invocation_meta = meta

    def _set_failure_metadata(self, attempts: list[dict[str, Any]]) -> None:
        meta = self._final_meta(attempts=attempts, selected_model=None)
        self._invocation_meta_var.set(meta)
        self._last_invocation_meta = meta

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,  # noqa: ANN001
        **kwargs: Any,
    ) -> ChatResult:
        attempts: list[dict[str, Any]] = []
        last_exc: Exception | None = None

        for model in self._models():
            try:
                result = model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self._record_attempt(attempts, model=model, success=False, error=exc)
                if not is_retryable_provider_error(exc):
                    self._set_failure_metadata(attempts)
                    raise
                continue

            self._set_success_metadata(attempts, model=model)
            return result

        self._set_failure_metadata(attempts)
        self._raise_all_failed(last_exc)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,  # noqa: ANN001
        **kwargs: Any,
    ) -> ChatResult:
        attempts: list[dict[str, Any]] = []
        last_exc: Exception | None = None

        for model in self._models():
            try:
                result = await model._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self._record_attempt(attempts, model=model, success=False, error=exc)
                if not is_retryable_provider_error(exc):
                    self._set_failure_metadata(attempts)
                    raise
                continue

            self._set_success_metadata(attempts, model=model)
            return result

        self._set_failure_metadata(attempts)
        self._raise_all_failed(last_exc)

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,  # noqa: ANN001
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        attempts: list[dict[str, Any]] = []
        last_exc: Exception | None = None

        for model in self._models():
            yielded_tokens = False
            try:
                for chunk in model._stream(messages, stop=stop, run_manager=run_manager, **kwargs):  # noqa: SLF001
                    yielded_tokens = True
                    yield chunk
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self._record_attempt(attempts, model=model, success=False, error=exc, yielded_tokens=yielded_tokens)
                if yielded_tokens or not is_retryable_provider_error(exc):
                    self._set_failure_metadata(attempts)
                    raise
                continue

            self._set_success_metadata(attempts, model=model, yielded_tokens=yielded_tokens)
            return

        self._set_failure_metadata(attempts)
        self._raise_all_failed(last_exc)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,  # noqa: ANN001
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        attempts: list[dict[str, Any]] = []
        last_exc: Exception | None = None

        for model in self._models():
            yielded_tokens = False
            try:
                async for chunk in model._astream(messages, stop=stop, run_manager=run_manager, **kwargs):  # noqa: SLF001
                    yielded_tokens = True
                    yield chunk
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self._record_attempt(attempts, model=model, success=False, error=exc, yielded_tokens=yielded_tokens)
                if yielded_tokens or not is_retryable_provider_error(exc):
                    self._set_failure_metadata(attempts)
                    raise
                continue

            self._set_success_metadata(attempts, model=model, yielded_tokens=yielded_tokens)
            return

        self._set_failure_metadata(attempts)
        self._raise_all_failed(last_exc)


def _build_chat_async_client(timeout: Any, pooled_async_client: Any) -> Any:
    if pooled_async_client is not None and settings.LLM_USE_POOLED_ASYNC_HTTP_CLIENT:
        return pooled_async_client
    # Build a dedicated async transport so LangChain/OpenAI does not inherit
    # unsupported SOCKS proxy env vars from the host shell in dev.
    return httpx.AsyncClient(trust_env=httpx_trust_env(logger=logger), timeout=timeout)


def build_chat_model_from_config(
    *,
    model_config: dict[str, Any] | None,
    http_client: Any,
    http_async_client: Any,
    streaming: bool,
) -> BaseChatModel:
    cfg = dict(model_config or {})
    model_name = str(cfg.get("model") or settings.LLM_MODEL or "").strip()
    base_url = normalize_openai_compatible_base_url(cfg.get("base_url") or settings.LLM_API_BASE)
    timeout = cfg.get("timeout", settings.LLM_TIMEOUT)
    common_kwargs = {
        "api_key": cfg.get("api_key") or settings.LLM_API_KEY,
        "base_url": base_url,
        "temperature": cfg.get("temperature", settings.LLM_TEMPERATURE),
        "streaming": bool(streaming),
        "timeout": timeout,
        "max_retries": cfg.get("max_retries", settings.LLM_MAX_RETRIES),
        "http_client": http_client,
        "http_async_client": _build_chat_async_client(timeout=timeout, pooled_async_client=http_async_client),
    }
    primary = PromptCacheChatOpenAI(model=model_name, **common_kwargs)

    if not bool(getattr(settings, "LLM_FALLBACK_ENABLED", False)):
        return primary

    fallbacks: list[BaseChatModel] = []
    seen_models = {model_name} if model_name else set()
    for spec in _resolve_fallback_specs(base_config=cfg):
        fallback_model_name = str(spec.get("model") or "").strip()
        if not fallback_model_name or fallback_model_name in seen_models:
            continue
        fallback_kwargs = dict(common_kwargs)
        fallback_kwargs["api_key"] = spec.get("api_key") or fallback_kwargs["api_key"]
        fallback_kwargs["base_url"] = normalize_openai_compatible_base_url(
            spec.get("base_url") or fallback_kwargs["base_url"]
        )
        fallback_kwargs["temperature"] = spec.get("temperature", fallback_kwargs["temperature"])
        fallback_kwargs["timeout"] = spec.get("timeout", fallback_kwargs["timeout"])
        fallback_kwargs["max_retries"] = spec.get("max_retries", fallback_kwargs["max_retries"])
        fallbacks.append(PromptCacheChatOpenAI(model=fallback_model_name, **fallback_kwargs))
        seen_models.add(fallback_model_name)

    if not fallbacks:
        return primary
    return FallbackChatOpenAI(primary=primary, fallbacks=fallbacks)
