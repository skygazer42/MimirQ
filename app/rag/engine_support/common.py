"""Shared constants, dataclasses, and stream_chat input plumbing for the RAG engine.

Must not import ``app.rag.engine`` or ``app.rag.retrieval.orchestrator``.
"""

from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from app.api.schemas.chat import ChatRAGConfig
from app.rag.core.logging import get_logger

logger = get_logger("rag.engine")
_RAG_ENGINE_FALLBACK_LOG_MESSAGE = "Ignoring non-critical RAG engine fallback failure: %s"

_UNABLE_TO_ANSWER_MESSAGE = "Unable to answer this question based on the available materials."


def _release_request_session(db: Any | None) -> None:
    if db is None:
        return
    try:
        db.rollback()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to release request DB session before async RAG work: %s", exc)


def _retrieval_error_from_debug(debug: dict[str, Any] | None) -> str | None:
    if not isinstance(debug, dict) or not bool(debug.get("all_retrieval_channels_failed")):
        return None
    reasons = debug.get("retrieval_degraded_reasons")
    details = sorted(
        f"{item.get('channel')}:{item.get('error_type')}"
        for item in (reasons if isinstance(reasons, list) else [])
        if isinstance(item, dict) and item.get("channel") and item.get("error_type")
    )
    suffix = ", ".join(details) if details else "unknown retrieval failure"
    return f"all retrieval channels failed: {suffix}"


@dataclass(frozen=True)
class RAGChatContext:
    history: list[dict[str, str]] | None = None
    conversation_id: UUID | None = None
    document_ids: list[UUID] | None = None
    tenant_id: UUID | None = None
    account_id: str | None = None
    dataset_id: UUID | None = None
    dataset_ids: list[UUID] | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class RAGResponseOptions:
    structured_output: bool = False
    structured_preset: str | None = None


@dataclass(frozen=True)
class RAGPromptSelection:
    prompt_template_id: UUID | None = None
    prompt_template_key: str | None = None
    prompt_ab_experiment_key: str | None = None
    rag_config_template: dict[str, Any] | None = None
    ab_user_key: str | None = None


_STREAM_CONTEXT_KEYS = {
    "history",
    "conversation_id",
    "document_ids",
    "tenant_id",
    "account_id",
    "dataset_id",
    "dataset_ids",
    "request_id",
}
_STREAM_RESPONSE_KEYS = {"structured_output", "structured_preset"}
_STREAM_PROMPT_KEYS = {
    "prompt_template_id",
    "prompt_template_key",
    "prompt_ab_experiment_key",
    "rag_config_template",
    "ab_user_key",
}
_STREAM_RAG_CONFIG_KEYS = set(ChatRAGConfig.model_fields)


def _pop_stream_chat_values(source: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in tuple(source):
        if key in keys:
            out[key] = source.pop(key)
    return out


def _resolve_stream_chat_inputs(
    *,
    context: RAGChatContext | None,
    rag_config: ChatRAGConfig | None,
    response_options: RAGResponseOptions | None,
    prompt_selection: RAGPromptSelection | None,
    legacy_overrides: dict[str, Any],
) -> tuple[RAGChatContext, ChatRAGConfig, RAGResponseOptions, RAGPromptSelection]:
    remaining = dict(legacy_overrides)

    context_updates = _pop_stream_chat_values(remaining, _STREAM_CONTEXT_KEYS)
    if context is None:
        context = RAGChatContext(**context_updates)
    elif context_updates:
        context = replace(context, **context_updates)

    rag_updates = _pop_stream_chat_values(remaining, _STREAM_RAG_CONFIG_KEYS)
    if rag_config is None:
        rag_config = ChatRAGConfig(**rag_updates)
    elif rag_updates:
        rag_config = rag_config.model_copy(update=rag_updates)

    response_updates = _pop_stream_chat_values(remaining, _STREAM_RESPONSE_KEYS)
    if response_options is None:
        response_options = RAGResponseOptions(**response_updates)
    elif response_updates:
        response_options = replace(response_options, **response_updates)

    prompt_updates = _pop_stream_chat_values(remaining, _STREAM_PROMPT_KEYS)
    if prompt_selection is None:
        prompt_selection = RAGPromptSelection(**prompt_updates)
    elif prompt_updates:
        prompt_selection = replace(prompt_selection, **prompt_updates)

    if remaining:
        unknown = ", ".join(sorted(remaining))
        raise TypeError(f"Unexpected stream_chat options: {unknown}")

    return (
        context or RAGChatContext(),
        rag_config or ChatRAGConfig(),
        response_options or RAGResponseOptions(),
        prompt_selection or RAGPromptSelection(),
    )
