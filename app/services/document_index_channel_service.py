"""Document index channel state helpers."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import case, literal
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from app.models.document import Document as DBDocument
from app.models.document_index_channel import DocumentIndexChannel
from app.services.pipeline_config import resolve_pipeline_effective

logger = logging.getLogger(__name__)

DOCUMENT_INDEX_CHANNELS = ("vector", "bm25", "kg", "event_vector", "entity_vector")
DOCUMENT_INDEX_CHANNEL_PROCESSING = "processing"
DOCUMENT_INDEX_CHANNEL_PENDING = "pending"
DOCUMENT_INDEX_CHANNEL_READY = "ready"
DOCUMENT_INDEX_CHANNEL_ERROR = "error"
DOCUMENT_INDEX_CHANNEL_DISABLED = "disabled"
DOCUMENT_INDEX_CHANNEL_SKIPPED = "skipped"
DOCUMENT_INDEX_CHANNEL_TERMINAL_READY = {"ready", "disabled", "skipped"}
DOCUMENT_INDEX_CHANNEL_TERMINAL_ERROR = {"error"}


@dataclass(frozen=True)
class DocumentIndexChannelSummary:
    pipeline_hash: str | None
    ready: bool
    pending_channels: list[str]
    error_channels: list[str]
    disabled_channels: list[str]
    required_channels: list[str]
    enabled_channels: list[str]
    statuses: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_hash": self.pipeline_hash,
            "ready": self.ready,
            "pending_channels": list(self.pending_channels),
            "error_channels": list(self.error_channels),
            "disabled_channels": list(self.disabled_channels),
            "required_channels": list(self.required_channels),
            "enabled_channels": list(self.enabled_channels),
            "statuses": {key: dict(value) for key, value in self.statuses.items()},
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _session_dialect_name(db: Session) -> str:
    get_bind = getattr(db, "get_bind", None)
    bind = get_bind() if callable(get_bind) else getattr(db, "bind", None)
    dialect = getattr(bind, "dialect", None)
    return str(getattr(dialect, "name", "") or "").strip().lower()


def _supports_atomic_postgresql_upsert(db: Session) -> bool:
    return _session_dialect_name(db) == "postgresql"


def normalize_document_index_channel(channel: str) -> str:
    normalized = str(channel or "").strip().lower()
    if normalized not in DOCUMENT_INDEX_CHANNELS:
        raise ValueError(f"unsupported document index channel: {channel}")
    return normalized


def _pipeline_hash_from_document(document: DBDocument, pipeline_hash: str | None = None) -> str | None:
    if pipeline_hash:
        return str(pipeline_hash).strip() or None
    meta = dict(getattr(document, "doc_metadata", None) or {})
    return str(meta.get("active_pipeline_hash") or meta.get("pipeline_hash") or "").strip() or None


def _effective_channel_flags(document: DBDocument) -> dict[str, bool]:
    meta = dict(getattr(document, "doc_metadata", None) or {})
    effective = resolve_pipeline_effective(document_metadata=meta)
    return {
        "vector": bool(getattr(effective, "chunk_vector_enabled", False)),
        "bm25": bool(getattr(effective, "bm25_index_enabled", False)),
        "kg": bool(getattr(effective, "kg_enabled", False)),
        "event_vector": bool(getattr(effective, "event_vector_enabled", False)),
        "entity_vector": bool(getattr(effective, "entity_vector_enabled", False)),
    }


def _legacy_channel_status(document: DBDocument, *, channel: str, enabled: bool) -> dict[str, Any]:
    status_raw = str(getattr(document, "status", "") or "").strip().lower()
    meta = dict(getattr(document, "doc_metadata", None) or {})
    active_ready = bool(meta.get("active_pipeline_ready")) or status_raw == "completed"

    if not enabled:
        status = "disabled"
    elif active_ready:
        status = "ready"
    elif status_raw in {"failed", "quarantined", "cancelled"}:
        status = "error"
    elif status_raw in {"processing"}:
        status = "processing"
    else:
        status = "pending"

    error = None
    if status == "error":
        error = str(getattr(document, "error_message", "") or meta.get("error_message") or "").strip() or None

    return {
        "channel": channel,
        "required": bool(enabled),
        "enabled": bool(enabled),
        "status": status,
        "error": error,
        "attempt_count": 0,
        "legacy": True,
    }


def _row_to_dict(row: DocumentIndexChannel) -> dict[str, Any]:
    return {
        "channel": str(getattr(row, "channel", "") or ""),
        "required": bool(getattr(row, "required", False)),
        "enabled": bool(getattr(row, "enabled", False)),
        "status": str(getattr(row, "status", "pending") or "pending").strip().lower(),
        "error": str(getattr(row, "error", "") or "").strip() or None,
        "attempt_count": int(getattr(row, "attempt_count", 0) or 0),
        "last_attempted_at": getattr(row, "last_attempted_at", None),
        "last_succeeded_at": getattr(row, "last_succeeded_at", None),
        "last_failed_at": getattr(row, "last_failed_at", None),
        "last_status_changed_at": getattr(row, "last_status_changed_at", None),
        "legacy": False,
    }


def _normalized_transition_state(
    *,
    document: DBDocument,
    channel: str,
    status: str,
    pipeline_hash: str | None,
    error: str | None,
    increment_attempt: bool,
) -> tuple[str, str, bool, str, str | None, bool] | None:
    normalized_channel = normalize_document_index_channel(channel)
    normalized_hash = _pipeline_hash_from_document(document, pipeline_hash=pipeline_hash)
    if not normalized_hash:
        return None
    enabled = bool(_effective_channel_flags(document).get(normalized_channel, False))
    normalized_status = str(status or DOCUMENT_INDEX_CHANNEL_PENDING).strip().lower() or DOCUMENT_INDEX_CHANNEL_PENDING
    if not enabled:
        return normalized_channel, normalized_hash, enabled, DOCUMENT_INDEX_CHANNEL_DISABLED, None, False
    return normalized_channel, normalized_hash, enabled, normalized_status, error, increment_attempt


def _transition_error_value(status: str, error: str | None) -> str | None:
    return (
        None
        if status in {DOCUMENT_INDEX_CHANNEL_READY, DOCUMENT_INDEX_CHANNEL_SKIPPED, DOCUMENT_INDEX_CHANNEL_DISABLED}
        else error
    )


def _existing_document_index_channel(
    db: Session,
    *,
    document: DBDocument,
    normalized_hash: str,
    normalized_channel: str,
) -> DocumentIndexChannel | None:
    with db.no_autoflush:
        return next(
            (
                row
                for row in list_document_index_channels(
                    db,
                    tenant_id=document.tenant_id,
                    document_id=document.id,
                    pipeline_hash=normalized_hash,
                )
                if str(getattr(row, "channel", "") or "") == normalized_channel
            ),
            None,
        )


def _transition_upsert_kwargs(
    *,
    document: DBDocument,
    normalized_hash: str,
    normalized_channel: str,
    enabled: bool,
    normalized_status: str,
    error: str | None,
    increment_attempt: bool,
    occurred_at: datetime,
    existing: DocumentIndexChannel | None = None,
    atomic: bool = False,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "tenant_id": document.tenant_id,
        "dataset_id": getattr(document, "dataset_id", None),
        "document_id": document.id,
        "pipeline_hash": normalized_hash,
        "channel": normalized_channel,
        "required": enabled,
        "enabled": enabled,
        "status": normalized_status,
        "error": _transition_error_value(normalized_status, error),
        "commit": False,
    }
    if existing is None:
        kwargs["last_attempted_at"] = occurred_at if increment_attempt else None
        kwargs["last_succeeded_at"] = (
            occurred_at if normalized_status in {DOCUMENT_INDEX_CHANNEL_READY, DOCUMENT_INDEX_CHANNEL_SKIPPED} else None
        )
        kwargs["last_failed_at"] = occurred_at if normalized_status == DOCUMENT_INDEX_CHANNEL_ERROR else None
        if atomic:
            kwargs["attempt_count"] = None
            kwargs["last_status_changed_at"] = occurred_at
            kwargs["attempt_count_increment"] = 1 if increment_attempt else 0
        else:
            kwargs["attempt_count"] = 1 if increment_attempt else 0
        return kwargs

    attempt_count = int(getattr(existing, "attempt_count", 0) or 0) + (1 if increment_attempt else 0)
    kwargs["attempt_count"] = attempt_count
    kwargs["last_attempted_at"] = occurred_at if increment_attempt else getattr(existing, "last_attempted_at", None)
    kwargs["last_succeeded_at"] = (
        occurred_at
        if normalized_status in {DOCUMENT_INDEX_CHANNEL_READY, DOCUMENT_INDEX_CHANNEL_SKIPPED}
        else getattr(existing, "last_succeeded_at", None)
    )
    kwargs["last_failed_at"] = (
        occurred_at if normalized_status == DOCUMENT_INDEX_CHANNEL_ERROR else getattr(existing, "last_failed_at", None)
    )
    return kwargs


def _finish_document_index_channel_write(
    db: Session, row: DocumentIndexChannel, *, commit: bool
) -> DocumentIndexChannel:
    if commit:
        db.commit()
        db.refresh(row)
    return row


def _log_document_index_channel_transition_failure(
    *,
    document: DBDocument,
    normalized_channel: str,
    normalized_status: str,
    exc: Exception,
    used_savepoint: bool,
) -> None:
    logger.warning(
        "Failed to persist document index channel transition%s tenant=%s document=%s channel=%s status=%s: %s",
        "" if used_savepoint else " without savepoint",
        getattr(document, "tenant_id", None),
        getattr(document, "id", None),
        normalized_channel,
        normalized_status,
        str(exc)[:200],
    )


def transition_document_index_channel(
    db: Session,
    *,
    document: DBDocument,
    channel: str,
    status: str,
    pipeline_hash: str | None = None,
    error: str | None = None,
    increment_attempt: bool = False,
    commit: bool = False,
) -> DocumentIndexChannel | None:
    normalized = _normalized_transition_state(
        document=document,
        channel=channel,
        status=status,
        pipeline_hash=pipeline_hash,
        error=error,
        increment_attempt=increment_attempt,
    )
    if normalized is None:
        return None
    normalized_channel, normalized_hash, enabled, normalized_status, error, increment_attempt = normalized
    occurred_at = _utcnow()

    def _persist() -> DocumentIndexChannel:
        if _supports_atomic_postgresql_upsert(db):
            kwargs = _transition_upsert_kwargs(
                document=document,
                normalized_hash=normalized_hash,
                normalized_channel=normalized_channel,
                enabled=enabled,
                normalized_status=normalized_status,
                error=error,
                increment_attempt=increment_attempt,
                occurred_at=occurred_at,
                atomic=True,
            )
            return upsert_document_index_channel(db, **kwargs)
        existing = _existing_document_index_channel(
            db,
            document=document,
            normalized_hash=normalized_hash,
            normalized_channel=normalized_channel,
        )
        kwargs = _transition_upsert_kwargs(
            document=document,
            normalized_hash=normalized_hash,
            normalized_channel=normalized_channel,
            enabled=enabled,
            normalized_status=normalized_status,
            error=error,
            increment_attempt=increment_attempt,
            occurred_at=occurred_at,
            existing=existing,
        )
        return upsert_document_index_channel(db, **kwargs)

    begin_nested = getattr(db, "begin_nested", None)
    if callable(begin_nested):
        try:
            with begin_nested():
                row = _persist()
            return _finish_document_index_channel_write(db, row, commit=commit)
        except Exception as exc:  # noqa: BLE001
            _log_document_index_channel_transition_failure(
                document=document,
                normalized_channel=normalized_channel,
                normalized_status=normalized_status,
                exc=exc,
                used_savepoint=True,
            )
            return None

    try:
        row = _persist()
        return _finish_document_index_channel_write(db, row, commit=commit)
    except Exception as exc:  # noqa: BLE001
        if hasattr(db, "rollback"):
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                logger.debug("Rollback after direct channel transition failure also failed", exc_info=True)
        _log_document_index_channel_transition_failure(
            document=document,
            normalized_channel=normalized_channel,
            normalized_status=normalized_status,
            exc=exc,
            used_savepoint=False,
        )
        return None


def list_document_index_channels(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    pipeline_hash: str | None,
) -> list[DocumentIndexChannel]:
    normalized_hash = str(pipeline_hash or "").strip()
    query = (
        db.query(DocumentIndexChannel)
        .filter(
            DocumentIndexChannel.tenant_id == tenant_id,
            DocumentIndexChannel.document_id == document_id,
        )
        .order_by(DocumentIndexChannel.channel.asc())
    )
    if normalized_hash:
        query = query.filter(DocumentIndexChannel.pipeline_hash == normalized_hash)
    return list(query.all())


def upsert_document_index_channel(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    document_id: UUID,
    pipeline_hash: str,
    channel: str,
    required: bool,
    enabled: bool,
    status: str,
    error: str | None = None,
    attempt_count: int | None = None,
    last_attempted_at: datetime | None = None,
    last_succeeded_at: datetime | None = None,
    last_failed_at: datetime | None = None,
    last_status_changed_at: datetime | None = None,
    attempt_count_increment: int = 0,
    commit: bool = False,
) -> DocumentIndexChannel:
    normalized_channel = normalize_document_index_channel(channel)
    normalized_hash = str(pipeline_hash or "").strip()
    normalized_status = str(status or "pending").strip().lower() or "pending"
    if not normalized_hash:
        raise ValueError("pipeline_hash is required")

    normalized_attempt_increment = max(0, int(attempt_count_increment or 0))
    normalized_attempt_count = max(0, int(attempt_count)) if attempt_count is not None else None
    occurred_at = last_status_changed_at or _utcnow()

    if _supports_atomic_postgresql_upsert(db):
        insert_values = _document_index_channel_insert_values(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            normalized_hash=normalized_hash,
            normalized_channel=normalized_channel,
            required=required,
            enabled=enabled,
            normalized_status=normalized_status,
            error=error,
            normalized_attempt_count=normalized_attempt_count,
            normalized_attempt_increment=normalized_attempt_increment,
            last_attempted_at=last_attempted_at,
            last_succeeded_at=last_succeeded_at,
            last_failed_at=last_failed_at,
            occurred_at=occurred_at,
        )
        stmt = postgresql_insert(DocumentIndexChannel).values(**insert_values)
        update_values = _document_index_channel_update_values(
            stmt=stmt,
            normalized_attempt_count=normalized_attempt_count,
            normalized_attempt_increment=normalized_attempt_increment,
            last_attempted_at=last_attempted_at,
            last_succeeded_at=last_succeeded_at,
            last_failed_at=last_failed_at,
            occurred_at=occurred_at,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_document_index_channels_identity",
            set_=update_values,
        ).returning(DocumentIndexChannel)
        row = db.execute(stmt).scalar_one()
        if commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
        return row

    row = (
        db.query(DocumentIndexChannel)
        .filter(
            DocumentIndexChannel.tenant_id == tenant_id,
            DocumentIndexChannel.document_id == document_id,
            DocumentIndexChannel.pipeline_hash == normalized_hash,
            DocumentIndexChannel.channel == normalized_channel,
        )
        .first()
    )
    previous_status = str(getattr(row, "status", "") or "").strip().lower() if row is not None else None
    if row is None:
        row = DocumentIndexChannel(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            pipeline_hash=normalized_hash,
            channel=normalized_channel,
        )
        db.add(row)

    _apply_document_index_channel_values(
        row=row,
        dataset_id=dataset_id,
        required=required,
        enabled=enabled,
        normalized_status=normalized_status,
        error=error,
        normalized_attempt_count=normalized_attempt_count,
        last_attempted_at=last_attempted_at,
        last_succeeded_at=last_succeeded_at,
        last_failed_at=last_failed_at,
        occurred_at=occurred_at,
        previous_status=previous_status,
    )

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def _document_index_channel_insert_values(
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    document_id: UUID,
    normalized_hash: str,
    normalized_channel: str,
    required: bool,
    enabled: bool,
    normalized_status: str,
    error: str | None,
    normalized_attempt_count: int | None,
    normalized_attempt_increment: int,
    last_attempted_at: datetime | None,
    last_succeeded_at: datetime | None,
    last_failed_at: datetime | None,
    occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "document_id": document_id,
        "pipeline_hash": normalized_hash,
        "channel": normalized_channel,
        "required": bool(required),
        "enabled": bool(enabled),
        "status": normalized_status,
        "error": str(error or "").strip()[:2000] or None,
        "attempt_count": normalized_attempt_count
        if normalized_attempt_count is not None
        else normalized_attempt_increment,
        "last_attempted_at": last_attempted_at,
        "last_succeeded_at": last_succeeded_at,
        "last_failed_at": last_failed_at,
        "last_status_changed_at": occurred_at,
    }


def _document_index_channel_update_values(
    *,
    stmt: Any,
    normalized_attempt_count: int | None,
    normalized_attempt_increment: int,
    last_attempted_at: datetime | None,
    last_succeeded_at: datetime | None,
    last_failed_at: datetime | None,
    occurred_at: datetime,
) -> dict[str, Any]:
    excluded = stmt.excluded
    current = DocumentIndexChannel
    attempt_count_update = (
        current.attempt_count + literal(normalized_attempt_increment)
        if normalized_attempt_increment > 0
        else (literal(normalized_attempt_count) if normalized_attempt_count is not None else current.attempt_count)
    )
    return {
        "dataset_id": excluded.dataset_id,
        "required": excluded.required,
        "enabled": excluded.enabled,
        "status": excluded.status,
        "error": excluded.error,
        "attempt_count": attempt_count_update,
        "last_attempted_at": excluded.last_attempted_at if last_attempted_at is not None else current.last_attempted_at,
        "last_succeeded_at": excluded.last_succeeded_at if last_succeeded_at is not None else current.last_succeeded_at,
        "last_failed_at": excluded.last_failed_at if last_failed_at is not None else current.last_failed_at,
        "last_status_changed_at": case(
            (current.status.is_distinct_from(excluded.status), literal(occurred_at)),
            else_=current.last_status_changed_at,
        ),
    }


def _apply_document_index_channel_values(
    *,
    row: DocumentIndexChannel,
    dataset_id: UUID | None,
    required: bool,
    enabled: bool,
    normalized_status: str,
    error: str | None,
    normalized_attempt_count: int | None,
    last_attempted_at: datetime | None,
    last_succeeded_at: datetime | None,
    last_failed_at: datetime | None,
    occurred_at: datetime,
    previous_status: str | None,
) -> None:
    row.dataset_id = dataset_id
    row.required = bool(required)
    row.enabled = bool(enabled)
    row.status = normalized_status
    row.error = str(error or "").strip()[:2000] or None
    if normalized_attempt_count is not None:
        row.attempt_count = normalized_attempt_count
    if last_attempted_at is not None:
        row.last_attempted_at = last_attempted_at
    if last_succeeded_at is not None:
        row.last_succeeded_at = last_succeeded_at
    if last_failed_at is not None:
        row.last_failed_at = last_failed_at
    if previous_status != normalized_status:
        row.last_status_changed_at = occurred_at


def reconcile_document_index_channels(
    db: Session,
    *,
    document: DBDocument,
    pipeline_hash: str | None = None,
    reset_enabled_to_pending: bool = False,
    commit: bool = False,
) -> list[DocumentIndexChannel]:
    normalized_hash = _pipeline_hash_from_document(document, pipeline_hash=pipeline_hash)
    if not normalized_hash:
        return []

    flags = _effective_channel_flags(document)
    existing = {
        str(row.channel): row
        for row in list_document_index_channels(
            db,
            tenant_id=document.tenant_id,
            document_id=document.id,
            pipeline_hash=normalized_hash,
        )
    }
    rows: list[DocumentIndexChannel] = []
    for channel in DOCUMENT_INDEX_CHANNELS:
        enabled = bool(flags.get(channel, False))
        row = existing.get(channel)
        status = str(getattr(row, "status", "") or "").strip().lower() if row is not None else ""
        error = str(getattr(row, "error", "") or "").strip() or None if row is not None else None
        attempt_count = int(getattr(row, "attempt_count", 0) or 0) if row is not None else 0
        if not enabled:
            status = "disabled"
            error = None
        elif reset_enabled_to_pending or not status or status == "disabled":
            status = "pending"
            error = None
        rows.append(
            upsert_document_index_channel(
                db,
                tenant_id=document.tenant_id,
                dataset_id=getattr(document, "dataset_id", None),
                document_id=document.id,
                pipeline_hash=normalized_hash,
                channel=channel,
                required=enabled,
                enabled=enabled,
                status=status,
                error=error,
                attempt_count=attempt_count,
                commit=False,
            )
        )
    if commit:
        db.commit()
        for row in rows:
            db.refresh(row)
    return rows


def repair_document_index_channels(
    db: Session,
    *,
    document: DBDocument,
    pipeline_hash: str | None = None,
    commit: bool = False,
) -> list[DocumentIndexChannel]:
    return reconcile_document_index_channels(
        db,
        document=document,
        pipeline_hash=pipeline_hash,
        reset_enabled_to_pending=False,
        commit=commit,
    )


def summarize_document_index_channels(
    db: Session,
    *,
    document: DBDocument,
    pipeline_hash: str | None = None,
) -> DocumentIndexChannelSummary:
    normalized_hash = _pipeline_hash_from_document(document, pipeline_hash=pipeline_hash)
    flags = _effective_channel_flags(document)
    rows = list_document_index_channels(
        db,
        tenant_id=document.tenant_id,
        document_id=document.id,
        pipeline_hash=normalized_hash,
    )
    statuses: dict[str, dict[str, Any]] = {}
    for row in rows:
        statuses[str(row.channel)] = _row_to_dict(row)
    for channel in DOCUMENT_INDEX_CHANNELS:
        if channel not in statuses:
            statuses[channel] = _legacy_channel_status(
                document, channel=channel, enabled=bool(flags.get(channel, False))
            )

    required_channels = [channel for channel, payload in statuses.items() if bool(payload.get("required"))]
    enabled_channels = [channel for channel, payload in statuses.items() if bool(payload.get("enabled"))]
    pending_channels = [
        channel
        for channel, payload in statuses.items()
        if bool(payload.get("enabled"))
        and str(payload.get("status") or "").strip().lower()
        not in DOCUMENT_INDEX_CHANNEL_TERMINAL_READY | DOCUMENT_INDEX_CHANNEL_TERMINAL_ERROR
    ]
    error_channels = [
        channel
        for channel, payload in statuses.items()
        if str(payload.get("status") or "").strip().lower() in DOCUMENT_INDEX_CHANNEL_TERMINAL_ERROR
    ]
    disabled_channels = [
        channel
        for channel, payload in statuses.items()
        if str(payload.get("status") or "").strip().lower() == "disabled"
    ]
    ready = not pending_channels and not error_channels
    return DocumentIndexChannelSummary(
        pipeline_hash=normalized_hash,
        ready=ready,
        pending_channels=pending_channels,
        error_channels=error_channels,
        disabled_channels=disabled_channels,
        required_channels=required_channels,
        enabled_channels=enabled_channels,
        statuses=statuses,
    )
