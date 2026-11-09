import hashlib
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.api.schemas.dify import DifyConversationTurnRequest, DifyConversationTurnResponse, DifyExternalKnowledgeRequest
from app.core.config import settings
from app.models.chat import Conversation, Message
from app.rag.core.logging import get_logger
from app.services.dify_integration.common import (
    _DIFY_TRACE_CITATION_METADATA_KEYS as _DIFY_TRACE_CITATION_METADATA_KEYS,
)
from app.services.dify_integration.common import _diagnostic_value_hash as _diagnostic_value_hash
from app.services.dify_integration.common import _first_nonempty_str as _first_nonempty_str
from app.services.dify_integration.common import _header_value as _header_value
from app.services.dify_integration.common import _uuid_or_none as _uuid_or_none
from app.services.external_conversation_ingest import _mimirq_citations_for_storage
from app.services.metrics_logger import log_metrics

logger = get_logger("app.services.dify_integration.conversation_turns")


def _dify_trace_source_conversation_id(headers: Mapping[str, str], body: DifyExternalKnowledgeRequest) -> str | None:
    body_conversation_id = body.conversation_id
    non_uuid_body_conversation_id = None
    if body_conversation_id is not None and _uuid_or_none(body_conversation_id) is None:
        non_uuid_body_conversation_id = str(body_conversation_id).strip()
    return _first_nonempty_str(
        body.source_conversation_id,
        body.dify_conversation_id,
        non_uuid_body_conversation_id,
        _header_value(headers, "x-mimirq-source-conversation-id"),
        _header_value(headers, "x-dify-conversation-id"),
        _header_value(headers, "x-source-conversation-id"),
    )


def _dify_trace_source_message_id(headers: Mapping[str, str], body: DifyExternalKnowledgeRequest) -> str | None:
    return _first_nonempty_str(
        body.source_message_id,
        body.dify_message_id,
        _header_value(headers, "x-mimirq-source-message-id"),
        _header_value(headers, "x-dify-message-id"),
        _header_value(headers, "x-source-message-id"),
    )


def _dify_trace_source_run_id(headers: Mapping[str, str], body: DifyExternalKnowledgeRequest) -> str | None:
    return _first_nonempty_str(
        body.source_run_id,
        body.dify_workflow_run_id,
        _header_value(headers, "x-mimirq-source-run-id"),
        _header_value(headers, "x-dify-workflow-run-id"),
        _header_value(headers, "x-source-run-id"),
    )


def _external_conversation_metadata_text(field: str):
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
    return row[0] if row else None


def _conversation_owner_matches_account(conversation: Conversation | None, *, account_id: str) -> bool:
    if conversation is None:
        return False
    owner_account_id = conversation.owner_account_id
    return bool(owner_account_id) and owner_account_id == account_id


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


def _ensure_dify_trace_conversation_accessible(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    account_id: str,
    source_conversation_id: str | None = None,
) -> Conversation:
    conversation = _load_dify_trace_conversation(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not _conversation_owner_matches_account(conversation, account_id=account_id):
        raise HTTPException(status_code=403, detail="Conversation is not accessible")
    expected_source_id = source_conversation_id
    if expected_source_id is not None:
        expected_source_id = expected_source_id.strip()
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


def _dify_turn_source_conversation_id(body: DifyConversationTurnRequest) -> str | None:
    body_conversation_id = body.conversation_id
    non_uuid_body_conversation_id = None
    if body_conversation_id is not None and _uuid_or_none(body_conversation_id) is None:
        non_uuid_body_conversation_id = str(body_conversation_id).strip()
    return _first_nonempty_str(
        body.source_conversation_id,
        body.dify_conversation_id,
        non_uuid_body_conversation_id,
    )


def _dify_turn_source_message_id(body: DifyConversationTurnRequest) -> str | None:
    return _first_nonempty_str(body.source_message_id, body.dify_message_id)


def _dify_turn_source_run_id(body: DifyConversationTurnRequest) -> str | None:
    return _first_nonempty_str(body.source_run_id, body.dify_workflow_run_id)


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
        Message.role.in__(("user", "assistant")),
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


def _lock_dify_conversation_turn_scope(*, db: Session, tenant_id: UUID, conversation_scope: str) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    digest = hashlib.sha256(f"dify-turn:{tenant_id}:{conversation_scope}".encode()).digest()
    lock_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    db.execute(sql_text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def _dify_turn_citations_for_storage(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _mimirq_citations_for_storage([item for item in citations if isinstance(item, dict)])


def _dify_trace_title(question: str) -> str:
    title = question.strip()
    return title[:80] if title else "Dify external retrieval"


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
    source_conversation_id = source_conversation_id.strip()
    if not source_conversation_id:
        return None

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
            existing = _load_dify_trace_conversation(db, tenant_id=tenant_id, conversation_id=existing_id)
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
            title=_dify_trace_title(question),
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
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.debug("Ignoring Dify trace conversation rollback failure", exc_info=True)
        logger.warning("Failed to ensure Dify trace conversation: %s", str(exc)[:200])
        return None


def persist_turn(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    body: DifyConversationTurnRequest,
) -> DifyConversationTurnResponse:
    source_conversation_id = _dify_turn_source_conversation_id(body)
    source_message_id = _dify_turn_source_message_id(body)
    source_run_id = _dify_turn_source_run_id(body)
    trace_request_id = body.trace_request_id
    question = body.query.strip()
    final_answer = body.answer.strip()
    if not question:
        raise HTTPException(status_code=400, detail="query is required")
    if not final_answer:
        raise HTTPException(status_code=400, detail="answer is required")

    conversation_id = _uuid_or_none(body.conversation_id)
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
        extra=body.metadata,
    )
    assistant_metadata = _dify_external_conversation_metadata(
        account_id=account_id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        source_run_id=source_run_id,
        trace_request_id=trace_request_id,
        role="assistant",
        extra=body.metadata,
    )
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
        reusable_user.message_metadata = {
            **user_metadata,
            "external_conversation": {
                **user_metadata["external_conversation"],
                "trace_seed": False,
                "turn_persisted": True,
            },
        }
        user_message = reusable_user
    else:
        user_message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="user",
            content=question,
            citations=[],
            message_metadata={
                **user_metadata,
                "external_conversation": {**user_metadata["external_conversation"], "turn_persisted": True},
            },
            created_at=now,
        )
        db.add(user_message)
        db.flush()

    assistant_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role="assistant",
        content=final_answer,
        citations=_dify_turn_citations_for_storage(body.citations),
        message_metadata={
            **assistant_metadata,
            "external_conversation": {**assistant_metadata["external_conversation"], "turn_persisted": True},
        },
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
        citations=body.citations,
    )
    return DifyConversationTurnResponse(
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        reused_user_message=reused_user_message,
    )


def resolve_trace_conversation_id(
    *,
    body: DifyExternalKnowledgeRequest,
    request_headers: Mapping[str, str],
    db: Session | None = None,
    tenant_id: UUID | None = None,
    account_id: str | None = None,
) -> UUID | None:
    source_conversation_id = _dify_trace_source_conversation_id(request_headers, body)
    body_conversation_id = _uuid_or_none(body.conversation_id)
    if body_conversation_id is not None:
        if db is not None and tenant_id is not None and account_id is not None:
            _ensure_dify_trace_conversation_accessible(
                db=db,
                tenant_id=tenant_id,
                conversation_id=body_conversation_id,
                account_id=account_id,
                source_conversation_id=source_conversation_id,
            )
        return body_conversation_id
    for header_name in ("x-mimirq-conversation-id", "x-conversation-id"):
        raw = _header_value(request_headers, header_name)
        if not raw:
            continue
        header_conversation_id = _uuid_or_none(raw)
        if header_conversation_id is not None:
            if db is not None and tenant_id is not None and account_id is not None:
                _ensure_dify_trace_conversation_accessible(
                    db=db,
                    tenant_id=tenant_id,
                    conversation_id=header_conversation_id,
                    account_id=account_id,
                    source_conversation_id=source_conversation_id,
                )
            return header_conversation_id
        logger.debug("Ignoring invalid Dify trace conversation header %s", header_name)
    if db is None or tenant_id is None or account_id is None or not source_conversation_id:
        return None
    return _ensure_dify_trace_conversation(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        source_conversation_id=source_conversation_id,
        source_message_id=_dify_trace_source_message_id(request_headers, body),
        source_run_id=_dify_trace_source_run_id(request_headers, body),
        question=body.query,
    )


def _dify_result_trace_citation(citation: dict[str, Any]) -> dict[str, Any]:
    safe = {key: citation.get(key) for key in _DIFY_TRACE_CITATION_METADATA_KEYS if citation.get(key) is not None}
    safe.setdefault("retrieval_mode", "dify_result")
    return safe


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
    final_answer = answer
    safe_citations = [item for item in citations if isinstance(item, dict)]
    log_metrics(
        {
            "event": "rag_trace",
            "source": "dify_result",
            "conversation_id": str(conversation_id),
            "tenant_id": str(tenant_id),
            "request_id": _first_nonempty_str(request_id) or f"dify-result-{uuid.uuid4().hex}",
            "question_hash": _diagnostic_value_hash(question),
            "retrieval": {
                "mode": "dify_result",
                "requested_mode": "dify_workflow",
                "top_k": 0,
                "query_count": 0,
                "errors": [],
                "enable_reranker": False,
            },
            "citations_count": len(safe_citations),
            "citations": [_dify_result_trace_citation(item) for item in safe_citations],
            "dify_result": {
                "status": "completed",
                "answer_chars": len(final_answer),
                "answer_hash": _diagnostic_value_hash(final_answer),
                "source_conversation_id": _first_nonempty_str(source_conversation_id),
                "source_message_id": _first_nonempty_str(source_message_id),
                "source_run_id": _first_nonempty_str(source_run_id),
                "citations_count": len(safe_citations),
            },
        }
    )


__all__ = [
    "_conversation_owner_matches_account",
    "_dify_external_conversation_metadata",
    "_dify_result_trace_citation",
    "_dify_trace_title",
    "_dify_turn_citations_for_storage",
    "_ensure_dify_trace_conversation",
    "_ensure_dify_trace_conversation_accessible",
    "_external_conversation_metadata_text",
    "_find_dify_trace_conversation",
    "_find_persisted_dify_conversation_turn",
    "_find_reusable_dify_seed_message",
    "_load_dify_trace_conversation",
    "_lock_dify_conversation_turn_scope",
    "_log_dify_result_rag_trace",
    "_dify_turn_source_conversation_id",
    "_dify_turn_source_message_id",
    "_dify_turn_source_run_id",
    "persist_turn",
    "resolve_trace_conversation_id",
]
