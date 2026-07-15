"""
Ingestion dashboard aggregates (admin-only, PII-safe).

Design goals:
- PII-safe: never return raw filenames/document contents; error taxonomy is normalized.
- Cheap: aggregate queries where possible; bounded scans for error reasons.
- Practical: works with current schema (processed_at may be null for many rows).
"""


import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import Document as DBDocument

_TERMINAL_STATUSES = ("completed", "failed", "quarantined", "cancelled")


def _now_utc() -> datetime:
    return datetime.now(UTC)

def _coerce_bucket_config(bucket_minutes: int) -> tuple[int, str]:
    """
    Clamp buckets to coarse hour/day units.

    We intentionally keep this logic DB-friendly (date_trunc('hour'|'day')).
    """
    bucket_minutes = int(bucket_minutes or 0)
    if bucket_minutes >= 24 * 60:
        return 24 * 60, "day"
    return 60, "hour"


def _build_time_buckets(*, since: datetime, now: datetime, trunc_unit: str) -> list[datetime]:
    """
    Build an inclusive list of bucket boundaries between since..now.

    `trunc_unit` must be 'hour' or 'day'.
    """
    if trunc_unit == "day":
        cursor = since.replace(hour=0, minute=0, second=0, microsecond=0)
        step = timedelta(days=1)
    else:
        cursor = since.replace(minute=0, second=0, microsecond=0)
        step = timedelta(hours=1)

    buckets: list[datetime] = []
    while cursor <= now:
        buckets.append(cursor)
        cursor = cursor + step
    return buckets


def _build_throughput_timeseries(
    *,
    buckets: list[datetime],
    bucket_counts: dict[datetime, dict[str, int]],
) -> dict[str, list[int]]:
    """
    Fill missing buckets with zeros to keep chart payloads stable.
    """
    ts_ms: list[int] = []
    completed: list[int] = []
    failed: list[int] = []
    quarantined: list[int] = []
    cancelled: list[int] = []

    for b in buckets:
        ts_ms.append(int(b.timestamp() * 1000))
        counts = bucket_counts.get(b, {})
        completed.append(int(counts.get("completed", 0)))
        failed.append(int(counts.get("failed", 0)))
        quarantined.append(int(counts.get("quarantined", 0)))
        cancelled.append(int(counts.get("cancelled", 0)))

    return {
        "ts_ms": ts_ms,
        "completed": completed,
        "failed": failed,
        "quarantined": quarantined,
        "cancelled": cancelled,
    }


def _normalize_error_reason(message: Any) -> str:
    """
    Turn a potentially noisy/PII-containing error message into a stable taxonomy key.

    Strategy:
    - Take the first line.
    - Take the prefix before ':' when present (many errors are "code: details").
    - Keep a conservative ASCII subset and bound the length.
    """
    raw = str(message or "").strip()
    if not raw:
        return "unknown"

    head = raw.splitlines()[0].strip()
    if ":" in head:
        head = head.split(":", 1)[0].strip()

    # Keep stable ASCII-ish tokens only; strip anything that looks like a path/url/payload.
    head = re.sub(r"[^A-Za-z0-9._-]+", "_", head)
    head = head.strip("_")
    if not head:
        return "unknown"
    return head[:80]


def summarize_ingestion_dashboard(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None = None,
    window_hours: int = 24,
    bucket_minutes: int = 60,
    max_error_samples: int = 5000,
    top_error_reasons: int = 12,
) -> dict[str, Any]:
    now = _now_utc()
    window_hours = max(1, min(int(window_hours or 24), 30 * 24))
    since = now - timedelta(hours=window_hours)

    # Clamp to coarse buckets (hour/day) to stay cheap and cross-DB friendly.
    bucket_minutes, trunc_unit = _coerce_bucket_config(int(bucket_minutes or 60))

    base_filters = [DBDocument.tenant_id == tenant_id, DBDocument.disabled_at.is_(None)]
    if dataset_id is not None:
        base_filters.append(DBDocument.dataset_id == dataset_id)

    # Current state distribution (backlog/health).
    rows = (
        db.query(DBDocument.status, func.count(DBDocument.id))
        .filter(*base_filters)
        .group_by(DBDocument.status)
        .all()
    )
    by_status: dict[str, int] = {str(status or "unknown"): int(cnt or 0) for status, cnt in rows}

    # Processing stage distribution (debug where time is spent).
    rows = (
        db.query(DBDocument.current_stage, func.count(DBDocument.id))
        .filter(*base_filters, DBDocument.status == "processing")
        .group_by(DBDocument.current_stage)
        .all()
    )
    by_stage_processing: dict[str, int] = {str(stage or "unknown"): int(cnt or 0) for stage, cnt in rows}

    # Created in window.
    try:
        created_raw = db.query(func.count(DBDocument.id)).filter(*base_filters, DBDocument.created_at >= since).scalar()
        created_count = int(created_raw or 0)
    except Exception:
        created_count = 0

    # Terminal throughput in window (bucket by updated_at; processed_at may be null).
    bucket_expr = func.date_trunc(trunc_unit, DBDocument.updated_at).label("bucket")
    rows = (
        db.query(bucket_expr, DBDocument.status, func.count(DBDocument.id))
        .filter(
            *base_filters,
            DBDocument.updated_at >= since,
            DBDocument.status.in_(_TERMINAL_STATUSES),
        )
        .group_by(bucket_expr, DBDocument.status)
        .order_by(bucket_expr.asc())
        .all()
    )

    bucket_counts: dict[datetime, dict[str, int]] = {}
    for bucket_dt, status, cnt in rows:
        if bucket_dt is None:
            continue
        key = str(status or "unknown")
        bucket_counts.setdefault(bucket_dt, {})[key] = int(cnt or 0)

    # Fill missing buckets for stable charts.
    buckets = _build_time_buckets(since=since, now=now, trunc_unit=trunc_unit)
    timeseries = _build_throughput_timeseries(buckets=buckets, bucket_counts=bucket_counts)

    # Error taxonomy (best-effort, bounded scan).
    error_reason_counts: Counter[str] = Counter()
    try:
        err_rows = (
            db.query(DBDocument.error_message)
            .filter(
                *base_filters,
                DBDocument.updated_at >= since,
                DBDocument.status.in_(("failed", "quarantined")),
            )
            .order_by(DBDocument.updated_at.desc())
            .limit(int(max_error_samples or 0) if int(max_error_samples or 0) > 0 else 0)
            .all()
        )
        for (msg,) in err_rows:
            error_reason_counts[_normalize_error_reason(msg)] += 1
    except Exception:
        error_reason_counts = Counter()

    top_errors = dict(error_reason_counts.most_common(max(0, int(top_error_reasons or 0))))

    # Best-effort: average time-to-complete for completed docs in window.
    avg_completed_sec: float | None = None
    try:
        secs = (
            db.query(func.avg(func.extract("epoch", DBDocument.updated_at - DBDocument.created_at)))
            .filter(
                *base_filters,
                DBDocument.updated_at >= since,
                DBDocument.status == "completed",
            )
            .scalar()
        )
        if secs is not None:
            avg_completed_sec = float(secs)
    except Exception:
        avg_completed_sec = None

    return {
        "window_hours": int(window_hours),
        "bucket_minutes": int(bucket_minutes),
        "window_start": since,
        "window_end": now,
        "dataset_id": str(dataset_id) if dataset_id is not None else None,
        "created_count": int(created_count),
        "by_status": dict(by_status),
        "by_stage_processing": dict(by_stage_processing),
        "avg_completed_latency_sec": avg_completed_sec,
        "top_error_reasons": top_errors,
        "timeseries": timeseries,
    }


__all__ = [
    "summarize_ingestion_dashboard",
]
