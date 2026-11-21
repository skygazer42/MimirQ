"""Shared document metadata writes, gate outcomes and processor logging."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.documents.records import Document as DBDocument

logger = logging.getLogger("parsing.document_processor")
_PROCESSOR_CLEANUP_LOG_MESSAGE = "Ignoring non-critical processor cleanup failure: %s"


def _log_processor_fallback(context: str, exc: BaseException) -> None:
    logger.debug("processor fallback failed in %s: %s", context, exc, exc_info=True)


def commit_and_refresh(db: Session, instance: object) -> None:
    """Commit once and refresh, preserving the producer's exception type.

    A commit callback can fail after the database has committed. The caller owns
    rollback and recovery; this function never retries the write.
    """
    db.commit()
    db.refresh(instance)


def _commit_document_metadata(db: Session, db_document: DBDocument, metadata: dict[str, Any]) -> None:
    db_document.doc_metadata = metadata
    commit_and_refresh(db, db_document)


def record_ingest_gate_outcome(
    metadata: dict[str, Any] | None,
    *,
    gate: str,
    outcome: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(metadata) if metadata is not None else {}
    existing = out.get("ingest_gate_outcomes")
    gate_outcomes = dict(existing) if isinstance(existing, dict) else {}
    entry: dict[str, Any] = {
        "gate": gate.strip() or "unknown",
        "outcome": outcome.strip() or "degraded",
        "reason": reason.strip() or "unknown",
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    if details is not None:
        for key, value in details.items():
            if value not in (None, "", [], {}):
                entry[key] = value
    gate_outcomes[entry["gate"]] = entry
    out["ingest_gate_outcomes"] = gate_outcomes
    return out


MIMIRQ_PARSE_DIRNAME = ".mimirq_parse"
REDACTED_MASK = "[REDACTED]"
# Redaction placeholder, not a credential.
SECRET_MASK = "[SECRET]"  # noqa: S105
