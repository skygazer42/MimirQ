"""
Conversation read/delete routes for the chat API.
"""

import contextlib
import json
import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Query as ORMQuery
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.chat import (
    ConversationCreate,
    ConversationDetail,
    ConversationList,
    ConversationSchema,
    ConversationUpdate,
)
from app.api.utils.response_headers import download_response_headers
from app.core.config import settings
from app.core.database import get_db
from app.models.chat import Conversation, Message
from app.services.audit_log_service import audit_log_event
from app.services.chat_conversation_access import (
    ensure_conversation_access,
    ensure_conversation_dataset_access,
)
from app.services.chat_conversation_titles import (
    CONVERSATION_TITLE_SOURCE_AUTO,
    CONVERSATION_TITLE_SOURCE_MANUAL,
    derive_auto_conversation_title,
    get_latest_user_message_content,
)
from app.services.chat_scope import enforce_non_empty_chat_scope
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids, get_allowed_document_id_sets

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}
CONVERSATION_NOT_FOUND_DETAIL = "Conversation not found"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _get_latest_messages_by_conversation_id(
    db: Session,
    tenant_id: UUID,
    conversation_ids: list[UUID],
) -> dict[UUID, Message]:
    if not conversation_ids:
        return {}

    latest_message_subq = (
        db.query(
            Message.id.label("id"),
            Message.conversation_id.label("conversation_id"),
            func.row_number()
            .over(
                partition_by=Message.conversation_id,
                order_by=(Message.created_at.desc(), Message.id.desc()),
            )
            .label("rn"),
        )
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id.in_(conversation_ids),
        )
        .subquery()
    )
    latest_messages = (
        db.query(Message)
        .join(latest_message_subq, Message.id == latest_message_subq.c.id)
        .filter(latest_message_subq.c.rn == 1)
        .all()
    )
    return {message.conversation_id: message for message in latest_messages}


def _apply_conversation_search(
    query: ORMQuery,
    *,
    tenant_id: UUID,
    search_term: str,
) -> ORMQuery:
    latest_message_content = (
        select(Message.content)
        .where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == Conversation.id,
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    return query.filter(
        or_(
            Conversation.title.icontains(search_term, autoescape=True),
            latest_message_content.icontains(search_term, autoescape=True),
        )
    )


def _normalized_conversation_limit(limit: int) -> int:
    try:
        limit_value = int(limit or 0)
    except Exception:
        limit_value = 20
    return max(1, min(limit_value, 200))


def _conversation_doc_ids_index(batch: list[Conversation]) -> tuple[dict[UUID, list[UUID]], set[UUID]]:
    doc_ids_by_conversation_id: dict[UUID, list[UUID]] = {}
    all_doc_ids: set[UUID] = set()
    for conv in batch:
        doc_ids = list(getattr(conv, "document_ids", None) or [])
        doc_ids_by_conversation_id[conv.id] = doc_ids
        all_doc_ids.update(doc_ids)
    return doc_ids_by_conversation_id, all_doc_ids


def _allowed_conversation_document_sets(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    all_doc_ids: set[UUID],
) -> tuple[set[UUID], set[UUID]]:
    if not all_doc_ids:
        return set(), set()
    return get_allowed_document_id_sets(
        db,
        tenant_id,
        account_id,
        list(all_doc_ids),
        check_member=False,
    )


def _dataset_scope_accessible(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    conv: Conversation,
    dataset_access: dict[UUID, bool],
) -> bool:
    dataset_id = getattr(conv, "dataset_id", None)
    if dataset_id is None:
        return True
    if dataset_id not in dataset_access:
        try:
            ensure_conversation_dataset_access(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                conv=conv,
            )
            dataset_access[dataset_id] = True
        except HTTPException:
            dataset_access[dataset_id] = False
    return dataset_access[dataset_id]


def _conversation_documents_accessible(
    *,
    doc_ids: list[UUID],
    allowed_doc_ids: set[UUID],
    missing_doc_ids: set[UUID],
) -> bool:
    if not doc_ids:
        return True
    remaining_doc_ids = set(doc_ids) - missing_doc_ids
    return not remaining_doc_ids or bool(remaining_doc_ids & allowed_doc_ids)


def _build_conversation_list_item(
    conv: Conversation,
    *,
    last_message_by_conversation_id: dict[UUID, Message],
) -> dict[str, object]:
    conv_dict: dict[str, object] = {
        "id": conv.id,
        "title": conv.title,
        "message_count": conv.message_count,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "last_message": None,
        "last_message_at": None,
    }
    last_msg = last_message_by_conversation_id.get(conv.id)
    if last_msg:
        conv_dict["last_message"] = last_msg.content[:100] + "..." if len(last_msg.content) > 100 else last_msg.content
        conv_dict["last_message_at"] = last_msg.created_at
    return conv_dict


def _collect_accessible_conversations(
    ordered_query: ORMQuery,
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    skip: int,
    limit_eff: int,
) -> tuple[int, list[Conversation]]:
    batch_size = max(50, limit_eff)
    query_offset = 0
    accessible_total = 0
    conversations: list[Conversation] = []
    dataset_access: dict[UUID, bool] = {}

    while True:
        batch = ordered_query.offset(query_offset).limit(batch_size).all()
        if not batch:
            break
        query_offset += len(batch)

        doc_ids_by_conversation_id, all_doc_ids = _conversation_doc_ids_index(batch)
        allowed_doc_ids, missing_doc_ids = _allowed_conversation_document_sets(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            all_doc_ids=all_doc_ids,
        )

        for conv in batch:
            if not _dataset_scope_accessible(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                conv=conv,
                dataset_access=dataset_access,
            ):
                continue
            doc_ids = doc_ids_by_conversation_id.get(conv.id) or []
            if not _conversation_documents_accessible(
                doc_ids=doc_ids,
                allowed_doc_ids=allowed_doc_ids,
                missing_doc_ids=missing_doc_ids,
            ):
                continue
            accessible_total += 1
            if accessible_total <= int(skip):
                continue
            if len(conversations) < limit_eff:
                conversations.append(conv)

        if len(batch) < batch_size:
            break

    return accessible_total, conversations


@router.post(
    "/conversations",
    response_model=ConversationSchema,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_conversation(
    request: ConversationCreate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new conversation."""
    allow_empty_docs = bool(getattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True))
    requested_title = str(request.title or "").strip()

    scope_dataset_id: UUID | None = None
    if request.document_ids:
        allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids)
        scope_dataset_id = None
    elif request.dataset_id is not None:
        DatasetService.ensure_member(db, tenant_id, account_id)
        ds = DatasetService.get_dataset(db, tenant_id, request.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)
        scope_dataset_id = request.dataset_id
        allowed_doc_ids = []
    else:
        scope_dataset_id = None
        allowed_doc_ids = []

    if not allow_empty_docs:
        enforce_non_empty_chat_scope(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            allowed_doc_ids=allowed_doc_ids,
            scope_dataset_id=scope_dataset_id,
            error_detail="No accessible documents for conversation",
        )

    conversation = Conversation(
        tenant_id=tenant_id,
        owner_account_id=str(account_id or "").strip() or None,
        title=requested_title or None,
        title_source=CONVERSATION_TITLE_SOURCE_MANUAL if requested_title else CONVERSATION_TITLE_SOURCE_AUTO,
        dataset_id=scope_dataset_id,
        document_ids=allowed_doc_ids,
    )

    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationSchema,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Update conversation metadata (currently: title)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail=CONVERSATION_NOT_FOUND_DETAIL)

    ensure_conversation_access(db, tenant_id, account_id, conversation)

    changed = False
    if "title" in getattr(payload, "model_fields_set", set()):
        title = (payload.title or "").strip()
        if title:
            conversation.title = title
            conversation.title_source = CONVERSATION_TITLE_SOURCE_MANUAL
        else:
            conversation.title_source = CONVERSATION_TITLE_SOURCE_AUTO
            conversation.title = derive_auto_conversation_title(
                get_latest_user_message_content(
                    db=db,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                )
            )
        changed = True

    if changed:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="chat.conversation.update",
            resource_type="conversation",
            resource_id=str(conversation_id),
            details={"title_chars": len((conversation.title or "").strip())},
        )
        db.commit()
        db.refresh(conversation)

    return conversation


@router.get("/conversations", response_model=ConversationList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_conversations(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    q: Annotated[str | None, Query(max_length=500)] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List conversations."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    normalized_account_id = str(account_id or "").strip()
    search_term = str(q or "").strip()
    query = db.query(Conversation).filter(
        Conversation.tenant_id == tenant_id,
        Conversation.owner_account_id == normalized_account_id,
    )
    if search_term:
        query = _apply_conversation_search(
            query,
            tenant_id=tenant_id,
            search_term=search_term,
        )

    # Fill the page with accessible conversations (avoid returning <limit when some are filtered).
    limit_eff = _normalized_conversation_limit(limit)
    accessible_total, conversations = _collect_accessible_conversations(
        query.order_by(Conversation.updated_at.desc()),
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        skip=int(skip),
        limit_eff=limit_eff,
    )

    result_items = []
    conv_ids = [conv.id for conv in conversations]
    last_message_by_conversation_id = _get_latest_messages_by_conversation_id(
        db,
        tenant_id,
        conv_ids,
    )

    for conv in conversations:
        result_items.append(
            _build_conversation_list_item(
                conv,
                last_message_by_conversation_id=last_message_by_conversation_id,
            )
        )

    result_items.sort(
        key=lambda item: item.get("last_message_at") or item.get("created_at") or item.get("updated_at"),
        reverse=True,
    )

    returned = len(result_items)
    total = accessible_total
    next_skip = int(skip) + returned
    has_more = next_skip < total

    return {
        "total": total,
        "returned": returned,
        "has_more": has_more,
        "next_skip": next_skip if has_more else None,
        "items": result_items,
    }


@router.get("/conversations/{conversation_id}/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_conversation(
    conversation_id: UUID,
    fmt: Annotated[str, Query(pattern="^(markdown|json)$")] = "markdown",
    include_citations: Annotated[bool, Query()] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export a conversation as a downloadable file.

    - fmt=markdown (default): text/markdown
    - fmt=json: application/json
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail=CONVERSATION_NOT_FOUND_DETAIL)

    ensure_conversation_access(db, tenant_id, account_id, conversation)

    messages = (
        db.query(Message)
        .filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )

    title = (conversation.title or "").strip() or f"Conversation {conversation_id}"

    if fmt == "json":
        payload = {
            "conversation_id": str(conversation_id),
            "title": title,
            "exported_at": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "citations": (m.citations if include_citations else None),
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        media_type = "application/json"
        suffix = "json"
    else:
        parts: list[str] = []
        parts.append(f"# {title}")
        parts.append("")
        parts.append(f"- conversation_id: `{conversation_id}`")
        parts.append(f"- exported_at_utc: `{datetime.now(UTC).replace(tzinfo=None).isoformat()}Z`")
        parts.append("")

        for m in messages:
            role = str(m.role or "").strip() or "unknown"
            parts.append(f"## {role}")
            parts.append("")
            parts.append(str(m.content or ""))
            parts.append("")

            if include_citations and role == "assistant" and isinstance(getattr(m, "citations", None), list):
                cites = m.citations or []
                if cites:
                    parts.append("### citations")
                    for c in cites[:20]:
                        if not isinstance(c, dict):
                            continue
                        doc_name = (str(c.get("document_name") or "") or "").strip()
                        doc_id = c.get("document_id")
                        chunk_index = c.get("chunk_index")
                        page = c.get("page_number")
                        snippet = (str(c.get("chunk_content") or "") or "").strip()
                        if len(snippet) > 260:
                            snippet = snippet[:260] + "..."
                        parts.append(
                            f"- {doc_name or 'Document'} (doc_id={doc_id}, chunk_index={chunk_index}, page={page}): {snippet}"
                        )
                    parts.append("")

        body = "\n".join(parts).strip() + "\n"
        media_type = "text/markdown; charset=utf-8"
        suffix = "md"

    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", title)[:80] or "conversation"
    filename = f"{safe_title}.{suffix}"
    headers = download_response_headers(filename)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="chat.conversation.export",
        resource_type="conversation",
        resource_id=str(conversation_id),
        details={"format": fmt, "include_citations": bool(include_citations), "messages": len(messages)},
    )
    with contextlib.suppress(Exception):
        db.commit()

    return Response(content=body, media_type=media_type, headers=headers)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationDetail,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_conversation_messages(
    conversation_id: UUID,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    before: Annotated[UUID | None, Query()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Fetch conversation history (paged)."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
        .first()
    )

    if not conversation:
        raise HTTPException(status_code=404, detail=CONVERSATION_NOT_FOUND_DETAIL)

    ensure_conversation_access(db, tenant_id, account_id, conversation)

    if before is not None and limit is None:
        raise HTTPException(status_code=400, detail="limit is required when before is set")

    query = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.tenant_id == tenant_id,
    )

    # Backwards compatible behavior: no limit => return all messages.
    if limit is None:
        messages = query.order_by(Message.created_at.asc()).all()
        return {
            "conversation_id": conversation_id,
            "returned": len(messages),
            "has_more": False,
            "messages": messages,
        }

    # Cursor pagination: request messages strictly older than the "before" message.
    if before is not None:
        before_msg = (
            db.query(Message)
            .filter(
                Message.id == before,
                Message.conversation_id == conversation_id,
                Message.tenant_id == tenant_id,
            )
            .first()
        )
        if before_msg is None:
            raise HTTPException(status_code=404, detail="Message cursor not found")
        query = query.filter(
            or_(
                Message.created_at < before_msg.created_at,
                and_(Message.created_at == before_msg.created_at, Message.id < before_msg.id),
            )
        )

    # Fetch latest-first for cheap paging, then reverse for display order.
    rows = query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    messages = list(reversed(rows))

    return {
        "conversation_id": conversation_id,
        "returned": len(messages),
        "has_more": has_more,
        "messages": messages,
    }


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def delete_conversation(
    conversation_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete a conversation."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
        .first()
    )

    if not conversation:
        raise HTTPException(status_code=404, detail=CONVERSATION_NOT_FOUND_DETAIL)

    ensure_conversation_access(db, tenant_id, account_id, conversation)

    db.delete(conversation)
    db.commit()

    return None
