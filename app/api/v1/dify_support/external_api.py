"""Dify HTTP authentication and conversation persistence adapters."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Header, HTTPException, Request
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.api.schemas.integrations import DifyConversationTurnResponse, DifyExternalKnowledgeRequest
from app.core.config import settings
from app.core.env import is_production_env
from app.models.chat import Conversation, Message
from app.rag.core.logging import get_logger
from app.services.dify_integration.auth import _coerce_uuid, _extract_bearer_token, _split_items, _token_matches
from app.services.dify_integration.common import (
    _DIFY_TRACE_CITATION_METADATA_KEYS,
    _first_nonempty_str,
    _uuid_or_none,
)
from app.services.dify_integration.scoring import _diagnostic_query_hash
from app.services.external_conversation_ingest import _mimirq_citations_for_storage
from app.services.metrics_logger import log_metrics
from app.types.dify_integration import DifyActor as _DifyActor

logger = get_logger("app.api.v1.integrations_dify")


def _request_client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first = forwarded_for.split(",", 1)[0].strip()
        if first:
            return first
    return request.client.host if request.client is not None else None


def _log_dify_result_rag_trace(
    *,
    tenant_id: UUID,
    conversation_id: UUID | None,
    request_id: str | None,
    question: str,
    answer: str,
    source_conversation_id: str | None,
    source_message_id: str | None,
    source_run_id: str | None,
    citations: list[dict[str, Any]],
) -> None:
    if conversation_id is None:
        return
    log_metrics(
        {
            "event": "rag_trace",
            "source": "dify_result",
            "conversation_id": str(conversation_id),
            "tenant_id": str(tenant_id),
            "request_id": _first_nonempty_str(request_id) or f"dify-result-{uuid.uuid4().hex}",
            "question_hash": _diagnostic_query_hash(question),
            "retrieval": {
                "mode": "dify_result",
                "requested_mode": "dify_workflow",
                "top_k": 0,
                "query_count": 0,
                "errors": [],
                "enable_reranker": False,
            },
            "citations_count": len(citations),
            "citations": [_dify_result_trace_citation(item) for item in citations],
            "dify_result": {
                "status": "completed",
                "answer_chars": len(answer),
                "answer_hash": _diagnostic_query_hash(answer),
                "source_conversation_id": _first_nonempty_str(source_conversation_id),
                "source_message_id": _first_nonempty_str(source_message_id),
                "source_run_id": _first_nonempty_str(source_run_id),
                "citations_count": len(citations),
            },
        }
    )


def _dify_result_trace_citation(citation: dict[str, Any]) -> dict[str, Any]:
    safe = {key: citation.get(key) for key in _DIFY_TRACE_CITATION_METADATA_KEYS if citation.get(key) is not None}
    safe.setdefault("retrieval_mode", "dify_result")
    return safe


def _dify_trace_source_conversation_id(request: Request, body: DifyExternalKnowledgeRequest) -> str | None:
    body_conversation_id = body.conversation_id
    non_uuid_body_conversation_id = None
    if body_conversation_id is not None and _uuid_or_none(body_conversation_id) is None:
        non_uuid_body_conversation_id = str(body_conversation_id).strip()
    return _first_nonempty_str(
        body.source_conversation_id,
        body.dify_conversation_id,
        non_uuid_body_conversation_id,
        request.headers.get("x-mimirq-source-conversation-id"),
        request.headers.get("x-dify-conversation-id"),
        request.headers.get("x-source-conversation-id"),
    )


def _dify_trace_source_message_id(request: Request, body: DifyExternalKnowledgeRequest) -> str | None:
    return _first_nonempty_str(
        body.source_message_id,
        body.dify_message_id,
        request.headers.get("x-mimirq-source-message-id"),
        request.headers.get("x-dify-message-id"),
        request.headers.get("x-source-message-id"),
    )


def _dify_trace_source_run_id(request: Request, body: DifyExternalKnowledgeRequest) -> str | None:
    return _first_nonempty_str(
        body.source_run_id,
        body.dify_workflow_run_id,
        request.headers.get("x-mimirq-source-run-id"),
        request.headers.get("x-dify-workflow-run-id"),
        request.headers.get("x-source-run-id"),
    )


def _external_conversation_metadata_text(field: str) -> ColumnElement[str]:
    return Message.message_metadata["external_conversation"][field].astext  # type: ignore[index]


def _find_dify_trace_conversation(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    source_conversation_id: str,
) -> UUID | None:
    row = (
        db.query(Message.conversation_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            Conversation.tenant_id == tenant_id,
            Conversation.owner_account_id == account_id,
            _external_conversation_metadata_text("source") == "dify",
            _external_conversation_metadata_text("source_conversation_id") == source_conversation_id,
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .first()
    )
    return row[0] if row is not None else None


def _conversation_owner_matches_account(conversation: Conversation | None, *, account_id: str) -> bool:
    if conversation is None:
        return False
    owner_account_id = conversation.owner_account_id
    if owner_account_id is not None:
        owner_account_id = owner_account_id.strip()
    return bool(owner_account_id) and owner_account_id == account_id


def _ensure_dify_trace_conversation_accessible(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    account_id: str,
    source_conversation_id: str | None = None,
) -> Conversation:

    conversation = _load_dify_trace_conversation(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not _conversation_owner_matches_account(conversation, account_id=account_id):
        raise HTTPException(status_code=403, detail="Conversation is not accessible")
    expected_source_id = source_conversation_id.strip() if source_conversation_id is not None else None
    if expected_source_id:
        bound_conversation_id = _find_dify_trace_conversation(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            source_conversation_id=expected_source_id,
        )
        if bound_conversation_id != conversation_id:
            raise HTTPException(status_code=403, detail="Conversation source does not match")
    return conversation


def _load_dify_trace_conversation(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter(Conversation.tenant_id == tenant_id, Conversation.id == conversation_id)
        .with_for_update()
        .first()
    )


def _dify_external_conversation_metadata(
    *,
    account_id: str,
    source_conversation_id: str | None,
    source_message_id: str | None,
    source_run_id: str | None,
    trace_request_id: str | None,
    role: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "external_conversation": {
            "source": "dify",
            "source_conversation_id": source_conversation_id,
            "source_message_id": source_message_id,
            "source_run_id": source_run_id,
            "trace_request_id": trace_request_id,
            "imported_by": account_id,
            "imported_at": datetime.now(UTC).isoformat(),
            "role": role,
        }
    }
    if extra:
        metadata["external_conversation"]["metadata"] = extra
    return metadata


def _find_reusable_dify_seed_message(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    source_conversation_id: str | None,
    source_message_id: str | None,
) -> Message | None:
    query = db.query(Message).filter(
        Message.tenant_id == tenant_id,
        Message.conversation_id == conversation_id,
        Message.role == "user",
        _external_conversation_metadata_text("source") == "dify",
        Message.message_metadata["external_conversation"]["trace_seed"].astext == "true",  # type: ignore[index]
    )
    if source_conversation_id:
        query = query.filter(_external_conversation_metadata_text("source_conversation_id") == source_conversation_id)
    if source_message_id:
        query = query.filter(_external_conversation_metadata_text("source_message_id") == source_message_id)
    return query.order_by(Message.created_at.asc(), Message.id.asc()).first()


def _find_persisted_dify_conversation_turn(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    source_conversation_id: str | None,
    source_message_id: str | None,
) -> tuple[Message, Message] | None:
    if not source_message_id:
        return None
    query = db.query(Message).filter(
        Message.tenant_id == tenant_id,
        Message.conversation_id == conversation_id,
        Message.role.in_(("user", "assistant")),
        _external_conversation_metadata_text("source") == "dify",
        _external_conversation_metadata_text("source_message_id") == source_message_id,
        _external_conversation_metadata_text("turn_persisted") == "true",
    )
    if source_conversation_id:
        query = query.filter(_external_conversation_metadata_text("source_conversation_id") == source_conversation_id)
    messages = query.order_by(Message.created_at.asc(), Message.id.asc()).all()
    user_message = next((message for message in messages if message.role == "user"), None)
    assistant_message = next((message for message in messages if message.role == "assistant"), None)
    if user_message is None or assistant_message is None:
        return None
    return user_message, assistant_message


def _lock_dify_conversation_turn_scope(
    *,
    db: Session,
    tenant_id: UUID,
    conversation_scope: str,
) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    digest = hashlib.sha256(f"dify-turn:{tenant_id}:{conversation_scope}".encode()).digest()
    lock_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    db.execute(sql_text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def _ensure_dify_trace_conversation(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    source_conversation_id: str,
    source_message_id: str | None,
    source_run_id: str | None,
    question: str,
) -> UUID | None:

    try:
        _lock_dify_conversation_turn_scope(
            db=db,
            tenant_id=tenant_id,
            conversation_scope=source_conversation_id,
        )
        existing_id = _find_dify_trace_conversation(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            source_conversation_id=source_conversation_id,
        )
        if existing_id is not None:
            existing = _load_dify_trace_conversation(
                db,
                tenant_id=tenant_id,
                conversation_id=existing_id,
            )
            if not _conversation_owner_matches_account(existing, account_id=account_id):
                logger.warning(
                    "Refusing to reuse Dify trace conversation across owners: tenant=%s source_conversation_id=%s",
                    tenant_id,
                    source_conversation_id,
                )
                return None
            return existing_id

        if not settings.DIFY_EXTERNAL_KNOWLEDGE_TRACE_AUTO_CREATE_CONVERSATION_ENABLED:
            return None

        now = datetime.now(UTC)
        conversation = Conversation(
            tenant_id=tenant_id,
            owner_account_id=account_id,
            title=question.strip()[:80] or "Dify external retrieval",
            title_source="auto",
            document_ids=[],
            message_count=1,
            updated_at=now,
        )
        db.add(conversation)
        db.flush()

        message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="user",
            content=question.strip() or source_conversation_id,
            citations=[],
            message_metadata={
                "external_conversation": {
                    "source": "dify",
                    "source_conversation_id": source_conversation_id,
                    "source_message_id": source_message_id,
                    "source_run_id": source_run_id,
                    "imported_by": account_id,
                    "imported_at": now.isoformat(),
                    "trace_seed": True,
                }
            },
            created_at=now,
        )
        db.add(message)
        db.commit()
        return conversation.id
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Failed to ensure Dify trace conversation: %s", str(exc)[:200], exc_info=True)
        return None


def _persist_dify_conversation_turn(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    query: str,
    answer: str,
    trace_request_id: str | None,
    source_conversation_id: str | None,
    source_message_id: str | None,
    source_run_id: str | None,
    citations: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    conversation_id: UUID | None = None,
) -> DifyConversationTurnResponse:

    if source_conversation_id is not None:
        source_conversation_id = source_conversation_id.strip()
    if source_message_id is not None:
        source_message_id = source_message_id.strip()
    if source_run_id is not None:
        source_run_id = source_run_id.strip()
    if trace_request_id is not None:
        trace_request_id = trace_request_id.strip()
        if trace_request_id == "":
            trace_request_id = None
    question = query.strip()
    final_answer = answer.strip()
    if not question:
        raise HTTPException(status_code=400, detail="query is required")
    if not final_answer:
        raise HTTPException(status_code=400, detail="answer is required")

    if conversation_id is not None:
        conversation_scope = source_conversation_id or str(conversation_id)
        _lock_dify_conversation_turn_scope(
            db=db,
            tenant_id=tenant_id,
            conversation_scope=conversation_scope,
        )
        conversation = _ensure_dify_trace_conversation_accessible(
            db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            account_id=account_id,
            source_conversation_id=source_conversation_id,
        )
    else:
        if not source_conversation_id:
            raise HTTPException(status_code=400, detail="dify_conversation_id is required")
        resolved_id = _ensure_dify_trace_conversation(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            source_conversation_id=source_conversation_id,
            source_message_id=source_message_id,
            source_run_id=source_run_id,
            question=question,
        )
        if resolved_id is None:
            raise HTTPException(status_code=503, detail="Failed to resolve Dify conversation")
        conversation = _load_dify_trace_conversation(db, tenant_id=tenant_id, conversation_id=resolved_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if not _conversation_owner_matches_account(conversation, account_id=account_id):
            raise HTTPException(status_code=403, detail="Conversation is not accessible")

    persisted_turn = _find_persisted_dify_conversation_turn(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
    )
    if persisted_turn is not None:
        user_message, assistant_message = persisted_turn
        return DifyConversationTurnResponse(
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            reused_user_message=True,
        )

    now = datetime.now(UTC)
    user_metadata = _dify_external_conversation_metadata(
        account_id=account_id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        source_run_id=source_run_id,
        trace_request_id=trace_request_id,
        role="user",
        extra=metadata,
    )
    assistant_metadata = _dify_external_conversation_metadata(
        account_id=account_id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        source_run_id=source_run_id,
        trace_request_id=trace_request_id,
        role="assistant",
        extra=metadata,
    )
    user_metadata["external_conversation"]["turn_persisted"] = True
    assistant_metadata["external_conversation"]["turn_persisted"] = True

    reusable_user = _find_reusable_dify_seed_message(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
    )
    reused_user_message = reusable_user is not None
    if reusable_user is not None:
        reusable_user.content = question
        user_metadata["external_conversation"]["trace_seed"] = False
        reusable_user.message_metadata = user_metadata
        user_message = reusable_user
    else:
        user_message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="user",
            content=question,
            citations=[],
            message_metadata=user_metadata,
            created_at=now,
        )
        db.add(user_message)
        db.flush()

    assistant_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role="assistant",
        content=final_answer,
        citations=_mimirq_citations_for_storage(citations),
        message_metadata=assistant_metadata,
        created_at=now,
    )
    db.add(assistant_message)
    db.flush()

    conversation.updated_at = now
    conversation.message_count = (
        db.query(Message).filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation.id).count()
    )
    db.commit()
    _log_dify_result_rag_trace(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        request_id=trace_request_id,
        question=question,
        answer=final_answer,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        source_run_id=source_run_id,
        citations=citations,
    )
    return DifyConversationTurnResponse(
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        reused_user_message=reused_user_message,
    )


def _dify_trace_conversation_id(
    request: Request,
    body: DifyExternalKnowledgeRequest,
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> UUID | None:

    source_conversation_id = _dify_trace_source_conversation_id(request, body)
    conversation_id = _uuid_or_none(body.conversation_id)
    for header_name in ("x-mimirq-conversation-id", "x-conversation-id"):
        if conversation_id is not None:
            break
        raw = request.headers.get(header_name)
        if not raw:
            continue
        conversation_id = _uuid_or_none(raw)
        if conversation_id is None:
            logger.debug("Ignoring invalid Dify trace conversation header %s", header_name)
    if conversation_id is not None:
        _ensure_dify_trace_conversation_accessible(
            db=db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            account_id=account_id,
            source_conversation_id=source_conversation_id,
        )
        return conversation_id

    if not source_conversation_id:
        return None
    return _ensure_dify_trace_conversation(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        source_conversation_id=source_conversation_id,
        source_message_id=_dify_trace_source_message_id(request, body),
        source_run_id=_dify_trace_source_run_id(request, body),
        question=body.query,
    )


def _require_dify_actor(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> _DifyActor:

    if not settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED:
        raise HTTPException(status_code=404, detail="Dify external knowledge is disabled")

    expected_tokens = _split_items(settings.DIFY_EXTERNAL_KNOWLEDGE_API_KEYS)
    if not expected_tokens:
        raise HTTPException(status_code=503, detail="Dify external knowledge API key is not configured")

    provided = _extract_bearer_token(authorization)
    if not any(_token_matches(provided, expected) for expected in expected_tokens):
        raise HTTPException(status_code=401, detail="Invalid Dify API key")

    raw_tenant = settings.DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID.strip()
    if not raw_tenant:
        if is_production_env():
            raise HTTPException(
                status_code=503,
                detail="Dify external knowledge tenant is not configured",
            )
        raw_tenant = str(request.headers.get(settings.TENANT_HEADER) or settings.DEFAULT_TENANT_ID).strip()
    tenant_id = _coerce_uuid(raw_tenant, label="Dify tenant id")
    account_id = settings.DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID.strip()
    if not account_id:
        raise HTTPException(status_code=503, detail="Dify external knowledge account is not configured")
    return _DifyActor(tenant_id=tenant_id, account_id=account_id)
