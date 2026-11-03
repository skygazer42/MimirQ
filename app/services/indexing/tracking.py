"""Owned tracking operations for indexing."""

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.document import Document as DBDocument
from app.services.document_index_channel_service import (
    transition_document_index_channel,
)

logger = logging.getLogger("indexer")

_INDEXER_FALLBACK_LOG_MESSAGE = "Ignoring non-critical indexer fallback failure: %s"


def load_document_for_channel_tracking(db: Session, *, tenant_id: UUID, document_id: UUID) -> DBDocument | None:
    return (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.id == document_id,
        )
        .first()
    )


def track_document_channel(
    db: Session,
    *,
    document: DBDocument | None,
    channel: str,
    status: str,
    error: str | None = None,
    increment_attempt: bool = False,
) -> None:
    if document is None:
        return
    transition_document_index_channel(
        db,
        document=document,
        channel=channel,
        status=status,
        error=error,
        increment_attempt=increment_attempt,
        commit=False,
    )
