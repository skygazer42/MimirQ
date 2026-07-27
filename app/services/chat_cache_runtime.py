
import asyncio
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.chat_response_cache import (
    InflightResponseLeaderCancelledError,
    acquire_inflight_chat_response,
    acquire_or_wait_for_distributed_inflight_chat_response,
    get_cached_chat_response_async,
    resolve_chat_response_cache_key,
    resolve_inflight_chat_response,
    set_cached_chat_response,
    wait_for_inflight_chat_response,
)
from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError


def annotate_chat_cache_metrics(
    metrics: dict[str, Any] | None,
    *,
    enabled: bool,
    hit: bool,
    skip_reason: str | None,
) -> dict[str, Any]:
    out = dict(metrics or {})
    out["chat_cache_enabled"] = bool(enabled)
    out["chat_cache_hit"] = bool(hit)
    if skip_reason:
        out["chat_cache_skip_reason"] = str(skip_reason)
    else:
        out.pop("chat_cache_skip_reason", None)
    return out


def annotate_chat_singleflight_metrics(
    metrics: dict[str, Any] | None,
    *,
    enabled: bool,
    hit: bool,
    role: str | None = None,
) -> dict[str, Any]:
    out = dict(metrics or {})
    out["chat_singleflight_enabled"] = bool(enabled)
    out["chat_singleflight_hit"] = bool(hit)
    if role:
        out["chat_singleflight_role"] = str(role)
    else:
        out.pop("chat_singleflight_role", None)
    return out


def store_chat_response_cache_if_needed(
    *,
    cache_eligible: bool,
    cache_hit: bool,
    cache_key: str | None,
    content: str,
    citations: list[dict[str, Any]] | list | None,
    metrics: dict[str, Any],
    structured_data: object | None,
) -> bool | None:
    if not (cache_eligible and (not cache_hit) and cache_key and (content or "").strip()):
        return None

    cache_payload = jsonable_encoder(
        {
            "content": content,
            "citations": citations if isinstance(citations, list) else [],
            "metrics": metrics,
            "structured_data": structured_data,
        }
    )
    stored = bool(set_cached_chat_response(cache_key, cache_payload))
    metrics.setdefault("chat_cache_store_ok", stored)
    return stored


@dataclass(frozen=True)
class ChatCacheLookupInput:
    db: Session
    tenant_id: UUID
    account_id: str
    dataset_id: UUID | None
    document_ids: list[UUID]
    history: list[Any]
    enable_long_term_memory: bool
    long_term_messages: list[dict]
    enable_structured_memory: bool
    question: str
    rag_config: dict[str, Any]
    prompt_config: dict[str, Any]
    structured_output: bool
    structured_preset: str | None
    use_graph: bool


@dataclass(frozen=True)
class PreparedNonStreamingChatCacheState:
    cache_feature_enabled: bool
    cache_key: str | None
    cache_skip_reason: str | None
    cache_eligible: bool
    cache_hit: bool
    singleflight_hit: bool
    singleflight_leader: bool
    singleflight_key: str | None
    full_response: str
    citations_data: list[Any]
    metrics_data: dict[str, Any]
    structured_data: object | None


def _resolve_chat_cache_lookup_input(
    *,
    options: ChatCacheLookupInput | None,
    legacy_overrides: dict[str, Any],
) -> ChatCacheLookupInput:
    if options is None:
        return ChatCacheLookupInput(**legacy_overrides)
    if not legacy_overrides:
        return options
    return cast(ChatCacheLookupInput, replace(options, **legacy_overrides))


def prepare_chat_cache_lookup(
    *,
    options: ChatCacheLookupInput | None = None,
    **legacy_overrides: Any,
) -> tuple[bool, str | None, str | None]:
    lookup = _resolve_chat_cache_lookup_input(options=options, legacy_overrides=legacy_overrides)
    cache_enabled = bool(getattr(settings, "CHAT_RESPONSE_CACHE_ENABLED", False))
    singleflight_enabled = bool(getattr(settings, "CHAT_RESPONSE_SINGLEFLIGHT_ENABLED", False))
    if not (cache_enabled or singleflight_enabled):
        return False, None, None
    if not lookup.document_ids and lookup.dataset_id is None:
        return cache_enabled, None, "missing_scope"
    if bool(getattr(settings, "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY", True)):
        if (
            lookup.history
            or lookup.enable_long_term_memory
            or lookup.long_term_messages
            or lookup.enable_structured_memory
        ):
            return cache_enabled, None, "history_not_empty"
    try:
        cache_key, skip_reason = resolve_chat_response_cache_key(
            db=lookup.db,
            tenant_id=lookup.tenant_id,
            account_id=lookup.account_id,
            dataset_id=lookup.dataset_id,
            document_ids=lookup.document_ids,
            question=lookup.question,
            rag_config=lookup.rag_config,
            prompt_config=lookup.prompt_config,
            structured_output=lookup.structured_output,
            structured_preset=lookup.structured_preset,
            use_graph=lookup.use_graph,
        )
    except Exception:
        return cache_enabled, None, "lookup_error"
    return cache_enabled, cache_key, skip_reason


async def prepare_non_streaming_chat_cache_state(
    *,
    options: ChatCacheLookupInput,
) -> PreparedNonStreamingChatCacheState:
    cache_feature_enabled, cache_key, cache_skip_reason = prepare_chat_cache_lookup(
        options=options,
    )
    cache_eligible = bool(cache_key)
    cached = await get_cached_chat_response_async(cache_key) if cache_feature_enabled and cache_key else None
    if isinstance(cached, dict):
        metrics_data = annotate_chat_cache_metrics(
            dict(cached.get("metrics") or {}),
            enabled=cache_feature_enabled,
            hit=True,
            skip_reason=None,
        )
        metrics_data = annotate_chat_singleflight_metrics(
            metrics_data,
            enabled=bool(getattr(settings, "CHAT_RESPONSE_SINGLEFLIGHT_ENABLED", False)),
            hit=False,
            role=None,
        )
        return PreparedNonStreamingChatCacheState(
            cache_feature_enabled=cache_feature_enabled,
            cache_key=cache_key,
            cache_skip_reason=cache_skip_reason,
            cache_eligible=cache_eligible,
            cache_hit=True,
            singleflight_hit=False,
            singleflight_leader=False,
            singleflight_key=None,
            full_response=str(cached.get("content") or ""),
            citations_data=(
                cached.get("citations")
                if isinstance(cached.get("citations"), list)
                else []
            ),
            metrics_data=metrics_data,
            structured_data=cached.get("structured_data"),
        )

    singleflight_hit = False
    singleflight_leader = False
    singleflight_key: str | None = None
    full_response = ""
    citations_data: list[Any] = []
    metrics_data: dict[str, Any] = {}
    structured_data: object | None = None
    singleflight_feature_enabled = bool(
        getattr(settings, "CHAT_RESPONSE_SINGLEFLIGHT_ENABLED", False)
    )
    response_cache_ttl_sec = max(
        0,
        int(getattr(settings, "CHAT_RESPONSE_CACHE_TTL_SEC", 300) or 0),
    )
    singleflight_wait_timeout_sec = max(
        1e-3,
        float(getattr(settings, "CHAT_RESPONSE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC", 60.0) or 0.0),
    )
    singleflight_key = cache_key if singleflight_feature_enabled and cache_key else None
    if singleflight_key:
        loop = asyncio.get_running_loop()
        singleflight_wait_deadline = loop.time() + singleflight_wait_timeout_sec
        while True:
            singleflight_leader, inflight_future = await acquire_inflight_chat_response(
                singleflight_key
            )
            if singleflight_leader:
                break
            try:
                remaining_wait_sec = singleflight_wait_deadline - loop.time()
                if remaining_wait_sec <= 0:
                    raise RetrievalAdmissionTimeoutError(singleflight_wait_timeout_sec)
                shared_payload = await wait_for_inflight_chat_response(
                    inflight_future,
                    timeout_sec=remaining_wait_sec,
                )
            except InflightResponseLeaderCancelledError:
                continue
            full_response = str(shared_payload.get("content") or "")
            citations_data = (
                shared_payload.get("citations")
                if isinstance(shared_payload.get("citations"), list)
                else []
            )
            metrics_data = annotate_chat_cache_metrics(
                dict(shared_payload.get("metrics") or {}),
                enabled=cache_feature_enabled,
                hit=False,
                skip_reason=cache_skip_reason,
            )
            metrics_data = annotate_chat_singleflight_metrics(
                metrics_data,
                enabled=singleflight_feature_enabled,
                hit=True,
                role="follower",
            )
            structured_data = shared_payload.get("structured_data")
            singleflight_hit = True
            break
        if singleflight_leader:
            distributed_leader, shared_payload = await acquire_or_wait_for_distributed_inflight_chat_response(
                singleflight_key,
                cache_enabled=cache_feature_enabled,
                response_cache_ttl_sec=response_cache_ttl_sec,
            )
            if not distributed_leader:
                shared_payload = shared_payload or {}
                resolve_inflight_chat_response(singleflight_key, shared_payload)
                full_response = str(shared_payload.get("content") or "")
                citations_data = (
                    shared_payload.get("citations")
                    if isinstance(shared_payload.get("citations"), list)
                    else []
                )
                metrics_data = annotate_chat_cache_metrics(
                    dict(shared_payload.get("metrics") or {}),
                    enabled=cache_feature_enabled,
                    hit=False,
                    skip_reason=cache_skip_reason,
                )
                metrics_data = annotate_chat_singleflight_metrics(
                    metrics_data,
                    enabled=singleflight_feature_enabled,
                    hit=True,
                    role="follower",
                )
                structured_data = shared_payload.get("structured_data")
                singleflight_hit = True
                singleflight_leader = False

    return PreparedNonStreamingChatCacheState(
        cache_feature_enabled=cache_feature_enabled,
        cache_key=cache_key,
        cache_skip_reason=cache_skip_reason,
        cache_eligible=cache_eligible,
        cache_hit=False,
        singleflight_hit=singleflight_hit,
        singleflight_leader=singleflight_leader,
        singleflight_key=singleflight_key,
        full_response=full_response,
        citations_data=citations_data,
        metrics_data=metrics_data,
        structured_data=structured_data,
    )
