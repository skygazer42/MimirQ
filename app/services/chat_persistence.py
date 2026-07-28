
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string
from app.rag.core.logging import get_logger
from app.services.chat_response_cache import resolve_inflight_chat_response
from app.services.chat_runtime import store_chat_response_cache_if_needed
from app.services.chat_turn_persistence import (
    ChatTurnPersistInput,
    persist_chat_turn_sync,
)
from app.services.metrics_logger import log_metrics

logger = get_logger(__name__)


@dataclass(frozen=True)
class ChatResponseFinalizationInput:
    db: Session
    tenant_id: UUID
    conversation_id: UUID
    account_id: str
    assistant_message_id: UUID
    request_id: str
    question: str
    document_count: int
    full_response: str
    citations: list
    metrics: dict
    structured_data: object | None
    dataset_id_used: UUID | None
    cache_eligible: bool
    cache_hit: bool
    cache_key: str | None
    singleflight_key: str | None
    singleflight_leader: bool
    request_enable_structured_memory: bool
    ip: str | None
    user_agent: str | None
    enable_online_eval: bool
    retrieval_mode_default: str | None


def _is_extractive_fallback_trace(metrics: dict[str, Any]) -> bool:
    return str(metrics.get("generation_fallback_kind") or "").strip() == "extractive_retrieval_summary"


def _retrieval_elapsed_seconds(metrics: dict[str, Any]) -> float | None:
    retrieval_elapsed_raw = (
        metrics.get("retrieval_elapsed_sec")
        if metrics.get("retrieval_elapsed_sec") is not None
        else metrics.get("elapsed_sec")
    )
    try:
        if retrieval_elapsed_raw is not None:
            candidate = float(retrieval_elapsed_raw)
            if candidate >= 0:
                return candidate
    except Exception:
        return None
    return None


def _compact_retrieval_errors(metrics: dict[str, Any]) -> list[str]:
    errors_raw = metrics.get("retrieval_errors") or metrics.get("errors") or []
    return [str(item)[:200] for item in errors_raw if str(item or "").strip()]


def _safe_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _fallback_rerank_elapsed_seconds(citations: list) -> float | None:
    values: list[float] = []
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        try:
            value = float(citation.get("rerank_elapsed_sec"))
        except (TypeError, ValueError, OverflowError):
            continue
        if value >= 0:
            values.append(value)
    return round(max(values), 3) if values else None


def _extractive_fallback_cost_attribution(
    *,
    metrics: dict[str, Any],
    citations: list,
    question: str,
) -> dict[str, Any]:
    per_query = [item for item in (metrics.get("retrieval_per_query") or []) if isinstance(item, dict)]
    if per_query:
        query_count = len(per_query)
        query_chars = sum(_safe_non_negative_int(item.get("query_chars")) for item in per_query)
        query_tokens = sum(_safe_non_negative_int(item.get("query_tokens")) for item in per_query)
    else:
        fallback_query = str(metrics.get("query_for_retrieval") or question or "")
        query_count = _safe_non_negative_int(metrics.get("retrieval_query_count")) or int(bool(fallback_query))
        query_chars = len(fallback_query)
        query_tokens = num_tokens_from_string(fallback_query) if fallback_query else 0
    retrieval_elapsed_sec = _retrieval_elapsed_seconds(metrics)

    return {
        "schema": "mimirq.cost_attribution.v1",
        "llm": {
            "model_used": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "source": "extractive_fallback",
        },
        "embeddings": {
            "provider": str(getattr(settings, "EMBEDDING_PROVIDER", "") or ""),
            "model": str(getattr(settings, "EMBEDDING_MODEL", "") or ""),
            "query_count": int(query_count),
            "query_chars": int(query_chars),
            "query_tokens": int(query_tokens),
            "source": "estimate",
        },
        "retrieval": {
            "elapsed_sec": round(float(retrieval_elapsed_sec or 0.0), 3),
            "rerank_elapsed_sec": _fallback_rerank_elapsed_seconds(citations),
            "vector_backend": str(metrics.get("vector_backend") or settings.VECTOR_BACKEND or ""),
            "query_count": int(query_count),
        },
    }


def _online_eval_contexts(citations: list) -> list[str]:
    contexts: list[str] = []
    for citation in citations or []:
        if hasattr(citation, "model_dump"):
            try:
                citation = citation.model_dump(mode="json")
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
        if not isinstance(citation, dict):
            continue
        text = str(citation.get("chunk_content") or citation.get("quote") or citation.get("text") or "").strip()
        if not text or text in contexts:
            continue
        contexts.append(text)
        if len(contexts) >= 24:
            break
    return contexts


def _online_eval_retrieval_mode(metrics: dict[str, Any], retrieval_mode_default: str | None) -> str | None:
    return str(metrics.get("retrieval_mode") or retrieval_mode_default or "") or None


def _resolve_singleflight_payload(options: ChatResponseFinalizationInput, metrics_out: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": options.full_response,
        "citations": options.citations,
        "metrics": metrics_out,
        "structured_data": options.structured_data,
    }


def _chat_turn_persist_input(options: ChatResponseFinalizationInput, metrics_out: dict[str, Any]) -> ChatTurnPersistInput:
    return ChatTurnPersistInput(
        tenant_id=options.tenant_id,
        conversation_id=options.conversation_id,
        account_id=options.account_id,
        assistant_message_id=options.assistant_message_id,
        request_id=options.request_id,
        question=options.question,
        document_count=options.document_count,
        content=options.full_response,
        citations=options.citations,
        metrics=metrics_out,
        dataset_id_used=options.dataset_id_used,
        cache_hit=options.cache_hit,
        ip=options.ip,
        user_agent=options.user_agent,
        enable_structured_memory=options.request_enable_structured_memory,
    )


def _maybe_enqueue_online_eval(options: ChatResponseFinalizationInput, metrics_out: dict[str, Any]) -> None:
    if not options.enable_online_eval:
        return
    try:
        from app.services.online_eval_service import maybe_enqueue_online_eval

        maybe_enqueue_online_eval(
            tenant_id=options.tenant_id,
            dataset_id=options.dataset_id_used,
            request_id=str(options.request_id),
            answer=str(options.full_response or ""),
            contexts=_online_eval_contexts(options.citations),
            retrieval_mode=_online_eval_retrieval_mode(metrics_out, options.retrieval_mode_default),
            citations_count=int(len(options.citations or [])),
        )
    except Exception as exc:
        logger.debug("Ignoring online evaluation enqueue failure: %s", exc)


def _log_extractive_fallback_rag_trace(
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    request_id: str,
    question: str,
    citations: list,
    metrics: dict[str, Any],
    retrieval_mode_default: str | None,
) -> None:
    if not _is_extractive_fallback_trace(metrics):
        return

    retrieval_mode_used = str(
        metrics.get("retrieval_mode") or retrieval_mode_default or ""
    ).strip()
    retrieval_elapsed_sec = _retrieval_elapsed_seconds(metrics)
    errors = _compact_retrieval_errors(metrics)

    payload: dict[str, Any] = {
        "event": "rag_trace",
        "conversation_id": str(conversation_id),
        "tenant_id": str(tenant_id),
        "request_id": str(request_id),
        "question": str(question or ""),
        "query_for_retrieval": str(metrics.get("query_for_retrieval") or question or ""),
        "citations_count": int(len(citations or [])),
        "citations": list(citations or []),
        "retrieval": {
            "mode": retrieval_mode_used or None,
            "elapsed_sec": retrieval_elapsed_sec,
            "errors": errors,
        },
        "route": "extractive_fallback",
        "vector_backend": metrics.get("vector_backend") or settings.VECTOR_BACKEND,
        "generation_fallback_kind": metrics.get("generation_fallback_kind"),
        "generation_fallback_reason": metrics.get("generation_fallback_reason"),
        "cost_attribution": _extractive_fallback_cost_attribution(
            metrics=metrics,
            citations=citations,
            question=question,
        ),
    }
    log_metrics(payload)


def finalize_chat_response_sync(
    *,
    options: ChatResponseFinalizationInput,
) -> dict[str, Any]:
    metrics_out = dict(options.metrics or {})

    _log_extractive_fallback_rag_trace(
        tenant_id=options.tenant_id,
        conversation_id=options.conversation_id,
        request_id=options.request_id,
        question=options.question,
        citations=options.citations,
        metrics=metrics_out,
        retrieval_mode_default=options.retrieval_mode_default,
    )

    _maybe_enqueue_online_eval(options, metrics_out)

    persist_chat_turn_sync(
        db=options.db,
        options=_chat_turn_persist_input(options, metrics_out),
    )

    store_chat_response_cache_if_needed(
        cache_eligible=options.cache_eligible,
        cache_hit=options.cache_hit,
        cache_key=options.cache_key,
        content=options.full_response,
        citations=options.citations,
        metrics=metrics_out,
        structured_data=options.structured_data,
    )

    if options.singleflight_key and options.singleflight_leader:
        resolve_inflight_chat_response(
            options.singleflight_key,
            jsonable_encoder(_resolve_singleflight_payload(options, metrics_out)),
        )

    return metrics_out
