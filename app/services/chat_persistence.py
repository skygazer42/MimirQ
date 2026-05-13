from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.services.chat_response_cache import resolve_inflight_chat_response
from app.services.chat_runtime import store_chat_response_cache_if_needed
from app.services.chat_turn_persistence import (
    persist_chat_turn_sync,
)


def finalize_chat_response_sync(
    *,
    db: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    account_id: str,
    assistant_message_id: UUID,
    request_id: str,
    question: str,
    document_count: int,
    full_response: str,
    citations: list,
    metrics: dict,
    structured_data: object | None,
    dataset_id_used: UUID | None,
    cache_eligible: bool,
    cache_hit: bool,
    cache_key: str | None,
    singleflight_key: str | None,
    singleflight_leader: bool,
    request_enable_structured_memory: bool,
    ip: str | None,
    user_agent: str | None,
    enable_online_eval: bool,
    retrieval_mode_default: str | None,
) -> dict[str, Any]:
    metrics_out = dict(metrics or {})

    if enable_online_eval:
        try:
            from app.services.online_eval_service import maybe_enqueue_online_eval

            contexts: list[str] = []
            for c in citations or []:
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
                tenant_id=tenant_id,
                dataset_id=dataset_id_used,
                request_id=str(request_id),
                answer=str(full_response or ""),
                contexts=contexts,
                retrieval_mode=str(
                    metrics_out.get("retrieval_mode") or retrieval_mode_default or ""
                )
                or None,
                citations_count=int(len(citations or [])),
            )
        except Exception:
            pass

    store_chat_response_cache_if_needed(
        cache_eligible=cache_eligible,
        cache_hit=cache_hit,
        cache_key=cache_key,
        content=full_response,
        citations=citations,
        metrics=metrics_out,
        structured_data=structured_data,
    )

    if singleflight_key and singleflight_leader:
        resolve_inflight_chat_response(
            singleflight_key,
            jsonable_encoder(
                {
                    "content": full_response,
                    "citations": citations,
                    "metrics": metrics_out,
                    "structured_data": structured_data,
                }
            ),
        )

    persist_chat_turn_sync(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        account_id=account_id,
        assistant_message_id=assistant_message_id,
        request_id=request_id,
        question=question,
        document_count=document_count,
        content=full_response,
        citations=citations,
        metrics=metrics_out,
        dataset_id_used=dataset_id_used,
        cache_hit=cache_hit,
        ip=ip,
        user_agent=user_agent,
        enable_structured_memory=request_enable_structured_memory,
    )

    return metrics_out
