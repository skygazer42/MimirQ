from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.chat import Conversation
from app.services.dataset_service import DatasetService
from app.services.document_access import get_allowed_document_id_sets

CONVERSATION_NOT_ACCESSIBLE_DETAIL = "Conversation is not accessible"


def _conversation_owner_account_id(conv: Conversation) -> str | None:
    owner_account_id = str(getattr(conv, "owner_account_id", "") or "").strip()
    return owner_account_id or None


def _ensure_conversation_owner(account_id: str, conv: Conversation) -> None:
    owner_account_id = _conversation_owner_account_id(conv)
    if not owner_account_id or owner_account_id != str(account_id or "").strip():
        raise HTTPException(status_code=403, detail=CONVERSATION_NOT_ACCESSIBLE_DETAIL)


def ensure_conversation_dataset_access(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    conv: Conversation,
) -> None:
    dataset_id = getattr(conv, "dataset_id", None)
    if dataset_id is None:
        return
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)


def ensure_conversation_access(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    conv: Conversation,
) -> list[UUID]:
    """
    Ensure the current user can access all documents bound to the conversation.
    Returns the allowed document ids, or an empty list if the conversation is unscoped.
    """
    _ensure_conversation_owner(account_id, conv)
    ensure_conversation_dataset_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        conv=conv,
    )
    if not conv.document_ids:
        return []
    doc_ids = list(conv.document_ids)
    allowed_ids, missing_ids = get_allowed_document_id_sets(
        db,
        tenant_id,
        account_id,
        doc_ids,
        check_member=False,
    )
    remaining = [doc_id for doc_id in doc_ids if doc_id not in missing_ids]
    if remaining != doc_ids:
        preserved_updated_at = getattr(conv, "updated_at", None)
        db.query(Conversation).filter(
            Conversation.id == conv.id,
            Conversation.tenant_id == tenant_id,
        ).update(
            {
                Conversation.document_ids: remaining,
                Conversation.updated_at: preserved_updated_at,
            },
            synchronize_session=False,
        )
        db.commit()
        db.refresh(conv)
    allowed = [doc_id for doc_id in remaining if doc_id in allowed_ids]
    if remaining and not allowed:
        raise HTTPException(status_code=403, detail="No accessible documents for this request")
    return allowed
