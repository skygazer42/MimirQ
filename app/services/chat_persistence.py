from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.chat_response_cache import resolve_inflight_chat_response
from app.services.chat_runtime import store_chat_response_cache_if_needed
from app.services.chat_turn_persistence import (
    ChatTurnPersistInput,
    persist_chat_turn_sync,
)
from app.services.metrics_logger import log_metrics


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
    if str(metrics.get("generation_fallback_kind") or "").strip() != "extractive_retrieval_summary":
        return

    retrieval_mode_used = str(
        metrics.get("retrieval_mode") or retrieval_mode_default or ""
    ).strip()
    retrieval_elapsed_raw = (
        metrics.get("retrieval_elapsed_sec")
        if metrics.get("retrieval_elapsed_sec") is not None
        else metrics.get("elapsed_sec")
    )
    retrieval_elapsed_sec: float | None = None
    try:
        if retrieval_elapsed_raw is not None:
            candidate = float(retrieval_elapsed_raw)
            if candidate >= 0:
                retrieval_elapsed_sec = candidate
    except Exception:
        retrieval_elapsed_sec = None

    errors_raw = metrics.get("retrieval_errors") or metrics.get("errors") or []
    errors = [str(item)[:200] for item in errors_raw if str(item or "").strip()]

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

    if options.enable_online_eval:
        try:
            from app.services.online_eval_service import maybe_enqueue_online_eval

            contexts: list[str] = []
            for c in options.citations or []:
                if hasattr(c, "model_dump"):
                    try:
                        c = c.model_dump(mode="json")
                    except Exception:
                        continue
                if not isinstance(c, dict):
                    continue
                text = str(
                    c.get("chunk_content") or c.get("quote") or c.get("text") or ""
                ).strip()
                if not text:
                    continue
                if text not in contexts:
                    contexts.append(text)
                if len(contexts) >= 24:
                    break

            maybe_enqueue_online_eval(
                tenant_id=options.tenant_id,
                dataset_id=options.dataset_id_used,
                request_id=str(options.request_id),
                answer=str(options.full_response or ""),
                contexts=contexts,
                retrieval_mode=str(
                    metrics_out.get("retrieval_mode") or options.retrieval_mode_default or ""
                )
                or None,
                citations_count=int(len(options.citations or [])),
            )
        except Exception:
            pass

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
            jsonable_encoder(
                {
                    "content": options.full_response,
                    "citations": options.citations,
                    "metrics": metrics_out,
                    "structured_data": options.structured_data,
                }
            ),
        )

    persist_chat_turn_sync(
        db=options.db,
        options=ChatTurnPersistInput(
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
        ),
    )

    return metrics_out
