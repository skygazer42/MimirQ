import re
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.chat import Conversation, Message

CONVERSATION_TITLE_SOURCE_AUTO = "auto"
CONVERSATION_TITLE_SOURCE_MANUAL = "manual"
_CONVERSATION_TITLE_PREVIEW_CHARS = 50


def derive_auto_conversation_title(message: str | None) -> str | None:
    text = re.sub(r"\s+", " ", str(message or "").strip())
    if not text:
        return None
    if len(text) <= _CONVERSATION_TITLE_PREVIEW_CHARS:
        return text
    return text[:_CONVERSATION_TITLE_PREVIEW_CHARS] + "..."


def get_conversation_title_source(conversation: Conversation) -> str:
    raw = str(getattr(conversation, "title_source", "") or "").strip().lower()
    if raw in {CONVERSATION_TITLE_SOURCE_AUTO, CONVERSATION_TITLE_SOURCE_MANUAL}:
        return raw
    return (
        CONVERSATION_TITLE_SOURCE_MANUAL
        if str(getattr(conversation, "title", "") or "").strip()
        else CONVERSATION_TITLE_SOURCE_AUTO
    )


def apply_auto_conversation_title(conversation: Conversation, message: str | None) -> None:
    if get_conversation_title_source(conversation) == CONVERSATION_TITLE_SOURCE_MANUAL:
        return
    conversation.title = derive_auto_conversation_title(message)
    conversation.title_source = CONVERSATION_TITLE_SOURCE_AUTO


def get_latest_user_message_content(
    *,
    db: Session,
    tenant_id: UUID,
    conversation_id: UUID,
) -> str | None:
    row = (
        db.query(Message.content)
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.role == "user",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .first()
    )
    if not row:
        return None
    return str(row[0] or "").strip() or None
