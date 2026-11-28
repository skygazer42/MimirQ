"""Check whether document evidence can apply to an explicitly current question."""

import re
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

NO_CURRENT_EVIDENCE = "no_current_evidence"

_CURRENT_EVIDENCE = re.compile(
    r"现行|在有效期内|仍然?有效|(?:当前|目前|现在)有效|有效的?(?:台账|文件|文档|依据|证据)"
    r"|\b(?:currently\s+(?:valid|effective|applicable|in force)"
    r"|(?:current(?:ly valid)?|valid|in[- ]force)\s+(?:\w+\s+)?"
    r"(?:ledger|document|policy|procedure|regulation|rules?|evidence))\b",
    re.IGNORECASE,
)
_HISTORICAL_EVIDENCE = re.compile(
    r"当时|曾经|历史|往年|此前|旧版|(?:截至|截止(?:到|至)?)\s*[:：]?\s*\d"
    r"|\b(?:historical|previously)\b|\bas\s+(?:of|at)\b(?!\s+(?:right\s+now|now|today)\b)\s+\S",
    re.IGNORECASE,
)


def requests_current_evidence(question: str) -> bool:
    # shortcut: match explicit wording, revisit when retrieval supports mixed historical and current scopes.
    return _CURRENT_EVIDENCE.search(question) is not None and _HISTORICAL_EVIDENCE.search(question) is None


def _document_boundary(value: object, *, observed_at: datetime) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        boundary = datetime.fromisoformat(value)
    except ValueError:
        return None
    return boundary if boundary.tzinfo is not None else boundary.replace(tzinfo=observed_at.tzinfo)


def outside_document_window(metadata: object, *, observed_at: datetime) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    start = _document_boundary(metadata.get("effective_at"), observed_at=observed_at)
    end = _document_boundary(metadata.get("expires_at"), observed_at=observed_at)
    if start is not None and end is not None and start >= end:
        return False
    return (start is not None and observed_at < start) or (end is not None and observed_at >= end)


def find_outside_window_document_ids(
    db: "Session", *, tenant_id: UUID, document_ids: set[UUID], observed_at: datetime
) -> set[UUID]:
    """Read validity for document IDs already scoped by the evidence caller."""
    from app.models.documents.records import Document

    rows = (
        db.query(Document.id, Document.doc_metadata)
        .filter(Document.tenant_id == tenant_id, Document.id.in_(document_ids))
        .all()
    )
    return {document_id for document_id, metadata in rows if outside_document_window(metadata, observed_at=observed_at)}
