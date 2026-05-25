from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import UUID

from app.rag.core.logging import get_logger
from app.services.chat_bootstrap_runtime import (
    PreparedChatRequestRuntime as PreparedChatRequestRuntime,
)
from app.services.chat_bootstrap_runtime import (
    PreparedChatTurnSession as PreparedChatTurnSession,
)
from app.services.chat_bootstrap_runtime import (
    PreparedStreamChatRuntime as PreparedStreamChatRuntime,
)
from app.services.chat_bootstrap_runtime import (
    prepare_chat_request_runtime as prepare_chat_request_runtime,
)
from app.services.chat_bootstrap_runtime import (
    prepare_chat_turn_session as prepare_chat_turn_session,
)
from app.services.chat_bootstrap_runtime import (
    prepare_stream_chat_runtime as prepare_stream_chat_runtime,
)
from app.services.chat_cache_runtime import (
    ChatCacheLookupInput as ChatCacheLookupInput,
)
from app.services.chat_cache_runtime import (
    PreparedNonStreamingChatCacheState as PreparedNonStreamingChatCacheState,
)
from app.services.chat_cache_runtime import (
    annotate_chat_cache_metrics as annotate_chat_cache_metrics,
)
from app.services.chat_cache_runtime import (
    annotate_chat_singleflight_metrics as annotate_chat_singleflight_metrics,
)
from app.services.chat_cache_runtime import (
    prepare_chat_cache_lookup as prepare_chat_cache_lookup,
)
from app.services.chat_cache_runtime import (
    prepare_non_streaming_chat_cache_state as prepare_non_streaming_chat_cache_state,
)
from app.services.chat_cache_runtime import (
    store_chat_response_cache_if_needed as store_chat_response_cache_if_needed,
)
from app.services.chat_execution_runtime import (
    ExecutedGraphChatOnceResult as ExecutedGraphChatOnceResult,
)
from app.services.chat_execution_runtime import (
    execute_graph_chat_once as execute_graph_chat_once,
)
from app.services.chat_execution_runtime import (
    execute_langchain_chat_once as execute_langchain_chat_once,
)

logger = get_logger("services.chat_runtime")


def apply_chat_runtime_metrics_context(
    metrics: dict[str, Any] | None,
    *,
    dataset_id_used: UUID | None,
    effective_prompt_template_id: UUID | None = None,
    effective_prompt_template_key: str | None = None,
    effective_prompt_ab_experiment_key: str | None = None,
    dataset_rag_defaults_applied_fields: list[str] | None = None,
    dataset_rag_config_template_defaults_applied_fields: list[str] | None = None,
    rag_config_template_meta: dict[str, Any] | None = None,
    dataset_prompt_defaults_applied_fields: list[str] | None = None,
    tenant_qps_meta: dict[str, Any] | None = None,
    quota_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(metrics or {})
    if dataset_id_used is not None:
        out.setdefault("dataset_id", str(dataset_id_used))
    if effective_prompt_template_id is not None:
        out.setdefault("prompt_template_id", str(effective_prompt_template_id))
    if effective_prompt_template_key:
        out.setdefault("prompt_template_key", effective_prompt_template_key)
    if effective_prompt_ab_experiment_key:
        out.setdefault("prompt_ab_experiment_key", effective_prompt_ab_experiment_key)
    if dataset_rag_defaults_applied_fields:
        out.setdefault("dataset_rag_defaults_applied", True)
        out.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)
    if dataset_rag_config_template_defaults_applied_fields:
        out.setdefault("dataset_rag_config_template_defaults_applied", True)
        out.setdefault(
            "dataset_rag_config_template_defaults_fields",
            dataset_rag_config_template_defaults_applied_fields,
        )
    if rag_config_template_meta:
        out.setdefault("rag_config_template", rag_config_template_meta)
    if dataset_prompt_defaults_applied_fields:
        out.setdefault("dataset_prompt_defaults_applied", True)
        out.setdefault("dataset_prompt_defaults_fields", dataset_prompt_defaults_applied_fields)
    if isinstance(tenant_qps_meta, dict) and tenant_qps_meta.get("enabled"):
        out.setdefault("tenant_qps_quota", tenant_qps_meta)
    if isinstance(quota_meta, dict) and quota_meta.get("enabled"):
        out.setdefault("quota", quota_meta)
    return out


@dataclass(frozen=True)
class ChatStreamPersistInput:
    tenant_id: UUID
    conversation_id: UUID
    account_id: str
    assistant_message_id: UUID
    request_id: str
    question: str
    document_count: int
    content: str
    citations: list
    metrics: dict
    dataset_id_used: UUID | None
    cache_hit: bool
    cache_key: str | None
    cache_eligible: bool
    structured_data: object | None
    ip: str | None
    user_agent: str | None
    enable_summary_memory: bool
    enable_structured_memory: bool


def _resolve_chat_stream_persist_input(
    *,
    options: ChatStreamPersistInput | None,
    legacy_overrides: dict[str, Any],
) -> ChatStreamPersistInput:
    if options is None:
        return ChatStreamPersistInput(**legacy_overrides)
    if not legacy_overrides:
        return options
    return cast(ChatStreamPersistInput, replace(options, **legacy_overrides))


def format_stream_error_message(exc: Exception) -> str:
    raw = str(exc) or exc.__class__.__name__
    raw = " ".join(raw.split())
    raw = re.sub(r"sk-[A-Za-z0-9]{8,}", "sk-***", raw)
    raw = re.sub(r"(?i)bearer\s+[A-Z0-9\-_.]{8,}", "Bearer ***", raw)
    status_code = getattr(exc, "status_code", None)
    if status_code and isinstance(status_code, int):
        raw = f"HTTP {status_code}: {raw}"
    return raw.strip()
