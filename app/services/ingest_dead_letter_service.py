
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.ingest_dead_letter import IngestDeadLetter
from app.rag.core.logging import get_logger

INGEST_DEAD_LETTER_SCHEMA_V1 = "mimirq.ingest_dead_letter.v1"
logger = get_logger(__name__)

_ERROR_CODE_ALIASES: tuple[tuple[str, str], ...] = (
    ("timeout", "timeout"),
    ("timed out", "timeout"),
    ("connection", "connection_error"),
    ("rate limit", "rate_limited"),
    ("429", "rate_limited"),
    ("quota", "quota_exceeded"),
    ("permission", "access_denied"),
    ("forbidden", "access_denied"),
    ("401", "access_denied"),
    ("403", "access_denied"),
    ("not found", "not_found"),
    ("missing", "not_found"),
    ("unsupported", "unsupported_file"),
    ("parse", "parse_failed"),
    ("chunk", "chunk_failed"),
    ("embedding", "embedding_failed"),
    ("vector", "vector_write_failed"),
    ("index", "index_failed"),
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _safe_str(value: object, *, max_len: int) -> str:
    return str(value or "").strip()[:max_len]


def normalize_ingest_error_code(value: object, *, fallback: str = "ingest_failed") -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback

    lower = raw.lower()
    for needle, code in _ERROR_CODE_ALIASES:
        if needle in lower:
            return code

    head = raw.splitlines()[0].strip()
    if ":" in head:
        head = head.split(":", 1)[0].strip()
    code = re.sub(r"[^A-Za-z0-9._-]+", "_", head).strip("_").lower()
    return code[:100] or fallback


def infer_failed_stage(*, failed_stage: object = None, current_stage: object = None) -> str:
    for raw in (failed_stage, current_stage):
        stage = _safe_str(raw, max_len=50).lower()
        if stage and stage not in {"failed", "error", "unknown"}:
            return stage
    return "unknown"


def record_ingest_dead_letter(
    db: Session,
    *,
    document: Any,
    failed_stage: str | None,
    error_message: str | None,
    error_code: str | None = None,
    original_payload: dict[str, Any] | None = None,
    producer_service: str = "document_processor",
) -> IngestDeadLetter:
    """
    Persist one open DLQ record per document and stamp structured failure fields.

    Repeated failures for the same document reuse the open dead letter and bump
    retry_count, keeping quarantine queues stable while preserving attempts.
    """

    now = _now_utc()
    stage = infer_failed_stage(failed_stage=failed_stage, current_stage=getattr(document, "current_stage", None))
    code = normalize_ingest_error_code(error_code or error_message)
    message = _safe_str(error_message, max_len=4000) or None

    if hasattr(document, "failed_stage"):
        document.failed_stage = stage
    if hasattr(document, "error_code"):
        document.error_code = code
    if hasattr(document, "processing_attempts"):
        try:
            document.processing_attempts = max(0, int(getattr(document, "processing_attempts", 0) or 0)) + 1
        except Exception:
            document.processing_attempts = 1
    if hasattr(document, "next_retry_at"):
        document.next_retry_at = None

    tenant_id = getattr(document, "tenant_id", None)
    document_id = getattr(document, "id", None)
    existing = None
    if tenant_id is not None and document_id is not None:
        existing = (
            db.query(IngestDeadLetter)
            .filter(
                IngestDeadLetter.tenant_id == tenant_id,
                IngestDeadLetter.document_id == document_id,
                IngestDeadLetter.status == "open",
            )
            .order_by(IngestDeadLetter.created_at.desc())
            .first()
        )

    payload = dict(original_payload or {})
    payload.setdefault("document_id", str(document_id) if document_id is not None else None)
    payload.setdefault("task_id", (getattr(document, "doc_metadata", None) or {}).get("task_id") if isinstance(getattr(document, "doc_metadata", None), dict) else None)
    payload.setdefault("pipeline_hash", (getattr(document, "doc_metadata", None) or {}).get("pipeline_hash") if isinstance(getattr(document, "doc_metadata", None), dict) else None)

    if existing is None:
        letter = IngestDeadLetter(
            tenant_id=tenant_id,
            dataset_id=getattr(document, "dataset_id", None),
            document_id=document_id,
            status="open",
            failed_stage=stage,
            error_code=code,
            error_message=message,
            source_ref=_safe_str(getattr(document, "filename", None) or getattr(document, "file_path", None), max_len=1000) or None,
            original_payload=payload,
            retry_count=0,
            producer_service=_safe_str(producer_service, max_len=80) or "document_processor",
            schema_version=INGEST_DEAD_LETTER_SCHEMA_V1,
            first_failed_at=now,
            last_attempt_at=now,
        )
        db.add(letter)
    else:
        letter = existing
        letter.dataset_id = getattr(document, "dataset_id", None)
        letter.failed_stage = stage
        letter.error_code = code
        letter.error_message = message
        letter.source_ref = _safe_str(getattr(document, "filename", None) or getattr(document, "file_path", None), max_len=1000) or None
        letter.original_payload = payload
        letter.retry_count = max(0, int(getattr(letter, "retry_count", 0) or 0)) + 1
        letter.last_attempt_at = now

    db.commit()
    try:
        db.refresh(letter)
    except Exception as exc:
        logger.debug("Ignoring ingest dead-letter refresh failure: %s", exc)
    return letter


def mark_dead_letter_replayed(db: Session, *, dead_letter: IngestDeadLetter) -> IngestDeadLetter:
    dead_letter.status = "replayed"
    dead_letter.replayed_at = _now_utc()
    db.commit()
    try:
        db.refresh(dead_letter)
    except Exception as exc:
        logger.debug("Ignoring replayed ingest dead-letter refresh failure: %s", exc)
    return dead_letter
