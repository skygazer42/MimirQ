from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.chat import Conversation
from app.services.chat_conversation_access import ensure_conversation_access
from app.services.chat_conversation_titles import (
    CONVERSATION_TITLE_SOURCE_AUTO,
    apply_auto_conversation_title,
)
from app.services.dataset_service import DatasetService
from app.services.document_access import (
    filter_allowed_document_ids,
    get_allowed_document_id_sets,
    list_accessible_document_ids,
)


@dataclass(frozen=True)
class ResolvedChatConversationScope:
    conversation: Conversation
    conversation_id: UUID
    scope_dataset_id: UUID | None
    allowed_doc_ids: list[UUID]


def _resolve_existing_conversation_document_scope(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    conversation: Conversation,
) -> list[UUID]:
    if not conversation.document_ids:
        return []
    doc_ids = list(conversation.document_ids)
    allowed_ids, missing_ids = get_allowed_document_id_sets(
        db,
        tenant_id,
        account_id,
        doc_ids,
        check_member=False,
    )
    remaining = [doc_id for doc_id in doc_ids if doc_id not in missing_ids]
    if remaining != doc_ids:
        conversation.document_ids = remaining
    allowed = [doc_id for doc_id in remaining if doc_id in allowed_ids]
    if allowed:
        return allowed
    if remaining:
        raise HTTPException(status_code=403, detail="No accessible documents for this request")
    raise HTTPException(
        status_code=409,
        detail="Conversation documents are no longer available; choose new documents or dataset scope",
    )


def _assert_requested_dataset_matches_document_scope(
    db: Session,
    *,
    tenant_id: UUID,
    request_dataset_id: UUID | None,
    allowed_doc_ids: list[UUID],
    mismatch_detail: str,
) -> None:
    if request_dataset_id is None or not allowed_doc_ids:
        return

    from app.models.document import Document as DBDocument  # noqa: WPS433

    rows = (
        db.query(DBDocument.dataset_id)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(allowed_doc_ids))
        .all()
    )
    dataset_ids = {row[0] for row in rows if row and row[0] is not None}
    if dataset_ids and dataset_ids != {request_dataset_id}:
        raise HTTPException(status_code=400, detail=mismatch_detail)


def enforce_non_empty_chat_scope(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    allowed_doc_ids: list[UUID],
    scope_dataset_id: UUID | None,
    error_detail: str,
) -> None:
    if allowed_doc_ids:
        return
    if scope_dataset_id is not None:
        from app.models.document import Document as DBDocument  # noqa: WPS433
        from app.services.dataset_profile_service import build_dataset_documents_query  # noqa: WPS433

        _, q = build_dataset_documents_query(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=scope_dataset_id,
        )
        q = q.filter(DBDocument.publication_status == "published")
        q = q.filter(
            (DBDocument.status == "completed")
            | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
        )
        if not q.with_entities(DBDocument.id).limit(1).first():
            raise HTTPException(status_code=400, detail=error_detail)
        return
    if not list_accessible_document_ids(db, tenant_id, account_id, status="completed", limit=1):
        raise HTTPException(status_code=400, detail=error_detail)


def resolve_chat_conversation_scope(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    conversation_id: UUID | None,
    request_document_ids: list[UUID] | None,
    request_dataset_id: UUID | None,
    request_message: str,
    allow_empty_docs: bool,
    allow_open_scope: bool,
    conversation_not_found_detail: str,
    dataset_required_detail: str,
    document_scope_mismatch_detail: str,
    empty_scope_detail: str,
) -> ResolvedChatConversationScope:
    scope_dataset_id: UUID | None = None
    allowed_doc_ids: list[UUID] = []

    if conversation_id:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
            .first()
        )
        if not conversation:
            raise HTTPException(status_code=404, detail=conversation_not_found_detail)
        ensure_conversation_access(db, tenant_id, account_id, conversation)

        if request_document_ids:
            allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request_document_ids)
            conversation.document_ids = allowed_doc_ids
            conversation.dataset_id = None
            _assert_requested_dataset_matches_document_scope(
                db,
                tenant_id=tenant_id,
                request_dataset_id=request_dataset_id,
                allowed_doc_ids=allowed_doc_ids,
                mismatch_detail=document_scope_mismatch_detail,
            )
        elif request_dataset_id is not None:
            DatasetService.ensure_member(db, tenant_id, account_id)
            dataset = DatasetService.get_dataset(db, tenant_id, request_dataset_id)
            DatasetService.assert_dataset_readable(db, dataset, account_id)

            scope_dataset_id = request_dataset_id
            conversation.dataset_id = request_dataset_id
            conversation.document_ids = []
            allowed_doc_ids = []
        elif conversation.document_ids:
            allowed_doc_ids = _resolve_existing_conversation_document_scope(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                conversation=conversation,
            )
            conversation.document_ids = allowed_doc_ids
            conversation.dataset_id = None
        else:
            scope_dataset_id = getattr(conversation, "dataset_id", None)
            allowed_doc_ids = []
            if scope_dataset_id is None and not allow_open_scope:
                raise HTTPException(status_code=400, detail=dataset_required_detail)
    else:
        if request_document_ids:
            allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request_document_ids)
            scope_dataset_id = None
            _assert_requested_dataset_matches_document_scope(
                db,
                tenant_id=tenant_id,
                request_dataset_id=request_dataset_id,
                allowed_doc_ids=allowed_doc_ids,
                mismatch_detail=document_scope_mismatch_detail,
            )
        elif request_dataset_id is not None:
            DatasetService.ensure_member(db, tenant_id, account_id)
            dataset = DatasetService.get_dataset(db, tenant_id, request_dataset_id)
            DatasetService.assert_dataset_readable(db, dataset, account_id)
            scope_dataset_id = request_dataset_id
            allowed_doc_ids = []
        else:
            scope_dataset_id = None
            allowed_doc_ids = []
            if not allow_open_scope:
                raise HTTPException(status_code=400, detail=dataset_required_detail)

        conversation = Conversation(
            id=uuid4(),
            tenant_id=tenant_id,
            owner_account_id=str(account_id or "").strip() or None,
            title_source=CONVERSATION_TITLE_SOURCE_AUTO,
            dataset_id=scope_dataset_id,
            document_ids=allowed_doc_ids,
        )
        apply_auto_conversation_title(conversation, request_message)
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id

    if not allow_empty_docs:
        enforce_non_empty_chat_scope(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            allowed_doc_ids=allowed_doc_ids,
            scope_dataset_id=scope_dataset_id,
            error_detail=empty_scope_detail,
        )

    return ResolvedChatConversationScope(
        conversation=conversation,
        conversation_id=conversation_id,
        scope_dataset_id=scope_dataset_id,
        allowed_doc_ids=allowed_doc_ids,
    )
