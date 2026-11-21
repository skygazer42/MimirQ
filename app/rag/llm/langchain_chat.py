import contextvars
import copy
import logging
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

import anyio
import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import ConfigDict, Field, PrivateAttr

from app.infrastructure.config import settings
from app.infrastructure.http.openai import normalize_openai_compatible_base_url
from app.rag.llm.factory import _resolve_fallback_specs
from app.rag.llm.fallback import AllProvidersFailedError, is_retryable_provider_error
from app.rag.llm.prompt_cache import (
    PromptCacheMetadata,
    annotate_openai_messages_for_prompt_cache,
    detect_anthropic_compatible,
)

if TYPE_CHECKING:
    from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
    from langchain_core.language_models import LanguageModelInput

logger = logging.getLogger("rag.llm.langchain_chat")
_ASYNC_CLEANUP_TIMEOUT_SEC = 5.0


class _ProviderAttempt(TypedDict):
    model: str | None
    success: bool
    yielded_tokens: bool
    error_type: NotRequired[str]
    error: NotRequired[str]


def _model_name_of(model: BaseChatModel) -> str | None:
    for attr in ("model_name", "model"):
        value = getattr(model, attr, None)
        if value:
            return str(value)
    return None


def _prompt_cache_meta(model: BaseChatModel) -> dict[str, Any]:
    getter = getattr(model, "get_last_payload_meta", None)
    if callable(getter):
        return dict(getter())
    return {}


async def _close_async_stream(stream: AsyncIterator[Any], *, pending_error: BaseException | None) -> None:
    close_stream = getattr(stream, "aclose", None)
    if close_stream is None:
        return
    try:
        with anyio.fail_after(_ASYNC_CLEANUP_TIMEOUT_SEC, shield=True):
            await close_stream()
    except BaseException as close_error:
        if pending_error is None or isinstance(pending_error, GeneratorExit):
            raise
        pending_error.add_note(f"Provider stream cleanup failed: {type(close_error).__name__}")
        logger.warning("Provider stream cleanup failed while propagating an error", exc_info=True)


class PromptCacheChatOpenAI(ChatOpenAI):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    _anthropic_compatible: bool = PrivateAttr(default=False)
    _payload_meta_var: contextvars.ContextVar[PromptCacheMetadata | None] = PrivateAttr(
        default_factory=lambda: contextvars.ContextVar("prompt_cache_chat_openai_meta", default=None)
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        base_url = normalize_openai_compatible_base_url(kwargs.get("base_url"))
        super().__init__(*args, **kwargs)
        self._anthropic_compatible = detect_anthropic_compatible(
            model_name=self.model_name,
            base_url=base_url,
        )

    def get_last_payload_meta(self) -> dict[str, Any]:
        return dict(self._payload_meta_var.get() or {})

    def _get_request_payload(
        self,
        input_: "LanguageModelInput",
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
                    "provider_anthropic_compatible": self._anthropic_compatible,
                }
            )
            return payload

        annotated, meta = annotate_openai_messages_for_prompt_cache(
            messages=raw_messages,
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

    def invoke(self, *args: Any, **kwargs: Any) -> BaseMessage:
        self._invocation_meta_var.set({})
        return super().invoke(*args, **kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> BaseMessage:
        self._invocation_meta_var.set({})
        return await super().ainvoke(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> Iterator[BaseMessage]:
        self._invocation_meta_var.set({})
        yield from super().stream(*args, **kwargs)

    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[BaseMessage]:
        self._invocation_meta_var.set({})
        stream = super().astream(*args, **kwargs)
        pending_error: BaseException | None = None
        try:
            async for chunk in stream:
                yield chunk
        except BaseException as operation_error:
            pending_error = operation_error
            raise
        finally:
            await _close_async_stream(stream, pending_error=pending_error)

    @property
    def _llm_type(self) -> str:
        return "fallback_chat_openai"

    @property
    def model_name(self) -> str | None:
        meta = self.get_last_invocation_meta()
        return meta.get("selected_model", _model_name_of(self.primary))

    @property
    def model(self) -> str | None:
        return self.model_name

    def get_last_invocation_meta(self) -> dict[str, Any]:
        return copy.deepcopy(self._invocation_meta_var.get() or {})

    def _update_invocation_metadata(self, meta: dict[str, Any]) -> None:
        current = self._invocation_meta_var.get()
        if current is None:
            self._invocation_meta_var.set(meta)
        else:
            # LangChain may run providers in child tasks. The invocation's
            # own holder remains visible to its caller, never to another call.
            current.clear()
            current.update(meta)

    def _models(self) -> list[BaseChatModel]:
        return [self.primary, *self.fallbacks]

    def _attempt_entry(
        self,
        *,
        model: BaseChatModel,
        success: bool,
        error: Exception | None = None,
        yielded_tokens: bool | None = False,
    ) -> _ProviderAttempt:
        entry: _ProviderAttempt = {
            "model": _model_name_of(model),
            "success": success,
            "yielded_tokens": bool(yielded_tokens),
        }
        if error is not None:
            entry["error_type"] = error.__class__.__name__
            entry["error"] = str(error)[:200]
        return entry

    def _final_meta(
        self,
        *,
        attempts: list[_ProviderAttempt],
        selected_model: str | None,
        prompt_cache: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cache = dict(prompt_cache or {})
        failure_count = sum(1 for attempt in attempts if not attempt["success"])
        return {
            "attempts": attempts,
            "failure_count": failure_count,
            "fallback_used": bool(selected_model and attempts and attempts[0]["model"] != selected_model),
            "selected_model": selected_model,
            "prompt_cache_applied": bool(cache.get("prompt_cache_applied")),
            "prompt_cache_message_count": int(cache.get("prompt_cache_message_count") or 0),
            "provider_anthropic_compatible": bool(cache.get("provider_anthropic_compatible")),
        }

    def _raise_all_failed(self, last_exc: Exception | None) -> None:
        raise AllProvidersFailedError("all LLM providers failed") from last_exc

    def _set_success_metadata(
        self,
        attempts: list[_ProviderAttempt],
        *,
        model: BaseChatModel,
        yielded_tokens: bool | None = None,
    ) -> None:
        prompt_cache = _prompt_cache_meta(model)
        selected_model = _model_name_of(model)
        attempts.append(self._attempt_entry(model=model, success=True, error=None, yielded_tokens=yielded_tokens))
        meta = self._final_meta(
            attempts=attempts,
            selected_model=selected_model,
            prompt_cache=prompt_cache,
        )
        self._update_invocation_metadata(meta)

    def _set_failure_metadata(self, attempts: list[_ProviderAttempt]) -> None:
        meta = self._final_meta(attempts=attempts, selected_model=None)
        self._update_invocation_metadata(meta)

    def _record_provider_failure(
        self,
        attempts: list[_ProviderAttempt],
        *,
        model: BaseChatModel,
        error: Exception,
        yielded_tokens: bool = False,
    ) -> bool:
        """Record the failure and return whether the next provider can be tried."""
        attempts.append(self._attempt_entry(model=model, success=False, error=error, yielded_tokens=yielded_tokens))
        retryable = not yielded_tokens and is_retryable_provider_error(error)
        if not retryable:
            self._set_failure_metadata(attempts)
        return retryable

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: "CallbackManagerForLLMRun | None" = None,
        **kwargs: Any,
    ) -> ChatResult:
        attempts: list[_ProviderAttempt] = []
        last_exc: Exception | None = None
        self._set_failure_metadata(attempts)

        for model in self._models():
            try:
                result = model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not self._record_provider_failure(attempts, model=model, error=exc):
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
        run_manager: "AsyncCallbackManagerForLLMRun | None" = None,
        **kwargs: Any,
    ) -> ChatResult:
        attempts: list[_ProviderAttempt] = []
        last_exc: Exception | None = None
        self._set_failure_metadata(attempts)

        for model in self._models():
            try:
                result = await model._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not self._record_provider_failure(attempts, model=model, error=exc):
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
        run_manager: "CallbackManagerForLLMRun | None" = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        attempts: list[_ProviderAttempt] = []
        last_exc: Exception | None = None
        self._set_failure_metadata(attempts)

        for model in self._models():
            yielded_tokens = False
            provider_error: Exception | None = None
            stream: Iterator[ChatGenerationChunk] | None = None
            pending_error: BaseException | None = None
            try:
                try:
                    stream = model._stream(messages, stop=stop, run_manager=run_manager, **kwargs)  # noqa: SLF001
                    for chunk in stream:
                        yielded_tokens = True
                        yield chunk
                except Exception as exc:  # noqa: BLE001
                    provider_error = exc
                    last_exc = exc
                    if not self._record_provider_failure(
                        attempts, model=model, error=exc, yielded_tokens=yielded_tokens
                    ):
                        raise
            except BaseException as operation_error:
                pending_error = operation_error
                raise
            finally:
                close_stream = getattr(stream, "close", None)
                if close_stream is not None:
                    try:
                        close_stream()
                    except BaseException as close_error:
                        if pending_error is None or isinstance(pending_error, GeneratorExit):
                            raise
                        pending_error.add_note(f"Provider stream cleanup failed: {type(close_error).__name__}")
                        logger.warning("Provider stream cleanup failed while propagating an error", exc_info=True)
            if provider_error is not None:
                continue

            self._set_success_metadata(attempts, model=model, yielded_tokens=yielded_tokens)
            return

        self._set_failure_metadata(attempts)
        self._raise_all_failed(last_exc)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: "AsyncCallbackManagerForLLMRun | None" = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        attempts: list[_ProviderAttempt] = []
        last_exc: Exception | None = None
        self._set_failure_metadata(attempts)

        for model in self._models():
            yielded_tokens = False
            provider_error: Exception | None = None
            stream: AsyncIterator[ChatGenerationChunk] | None = None
            pending_error: BaseException | None = None
            try:
                try:
                    stream = model._astream(messages, stop=stop, run_manager=run_manager, **kwargs)  # noqa: SLF001
                    async for chunk in stream:
                        yielded_tokens = True
                        yield chunk
                except Exception as exc:  # noqa: BLE001
                    provider_error = exc
                    last_exc = exc
                    if not self._record_provider_failure(
                        attempts, model=model, error=exc, yielded_tokens=yielded_tokens
                    ):
                        raise
            except BaseException as operation_error:
                pending_error = operation_error
                raise
            finally:
                if stream is not None:
                    await _close_async_stream(stream, pending_error=pending_error)
            if provider_error is not None:
                continue

            self._set_success_metadata(attempts, model=model, yielded_tokens=yielded_tokens)
            return

        self._set_failure_metadata(attempts)
        self._raise_all_failed(last_exc)


def build_chat_model_from_config(
    *,
    model_config: dict[str, Any] | None,
    http_client: httpx.Client | None,
    http_async_client: httpx.AsyncClient,
    streaming: bool,
) -> BaseChatModel:
    cfg = dict(model_config or {})
    model_name = str(cfg.get("model") or settings.LLM_MODEL).strip()
    base_url = normalize_openai_compatible_base_url(cfg.get("base_url") or settings.LLM_API_BASE)
    timeout = cfg.get("timeout", settings.LLM_TIMEOUT)
    common_kwargs: dict[str, Any] = {
        "api_key": cfg.get("api_key") or settings.LLM_API_KEY,
        "base_url": base_url,
        "temperature": cfg.get("temperature", settings.LLM_TEMPERATURE),
        "streaming": streaming,
        "timeout": timeout,
        "max_retries": cfg.get("max_retries", settings.LLM_MAX_RETRIES),
        "http_client": http_client,
        "http_async_client": http_async_client,
    }
    primary = PromptCacheChatOpenAI(model=model_name, **common_kwargs)

    if not settings.LLM_FALLBACK_ENABLED:
        return primary

    fallbacks: list[BaseChatModel] = []
    seen_models = {model_name} if model_name else set()
    for spec in _resolve_fallback_specs(base_config=cfg):
        fallback_model_name = spec["model"]
        if fallback_model_name in seen_models:
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
