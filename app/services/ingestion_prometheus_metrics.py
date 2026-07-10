"""
Prometheus metrics for ingestion runs (best-effort, PII-safe).

Design goals:
- Metrics must not include filenames/paths/URLs.
- Keep labels low-cardinality: use only `status`, `kind`, and `stage` (bounded).
- Optional: enabled only when PROMETHEUS_ENABLED=true.
"""


import re

from prometheus_client import Counter, Gauge, Histogram

from app.core.config import settings

INGESTION_RUNS_TOTAL = Counter(
    "ingestion_runs_total",
    "Total ingestion runs",
    ["status", "kind"],
)
INGESTION_RUN_DURATION_SECONDS = Histogram(
    "ingestion_run_duration_seconds",
    "Ingestion run duration in seconds",
    ["status", "kind"],
    buckets=(1, 2, 5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200, 14400, 28800),
)

INGESTION_PROCESSING_STAGE_TOTAL = Gauge(
    "ingestion_processing_stage_total",
    "Documents currently in processing status by stage",
    ["stage"],
)


def _enabled() -> bool:
    return bool(getattr(settings, "PROMETHEUS_ENABLED", False))


def _norm_kind(value: str | None) -> str:
    s = str(value or "").strip().lower()
    s = re.sub(r"[^a-z0-9._:-]+", "_", s)
    return (s[:80] or "unknown").strip("_") or "unknown"


def _norm_status(value: str | None) -> str:
    s = str(value or "").strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "_", s)
    return (s[:32] or "unknown").strip("_") or "unknown"


def _norm_stage(value: str | None) -> str:
    s = str(value or "").strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "_", s)
    return (s[:64] or "unknown").strip("_") or "unknown"


def observe_ingestion_run_created(*, kind: str | None) -> None:
    if not _enabled():
        return
    INGESTION_RUNS_TOTAL.labels(status="created", kind=_norm_kind(kind)).inc()


def observe_ingestion_run_finished(*, kind: str | None, status: str | None, duration_sec: float | None) -> None:
    if not _enabled():
        return

    k = _norm_kind(kind)
    st = _norm_status(status)
    INGESTION_RUNS_TOTAL.labels(status=st, kind=k).inc()

    if duration_sec is None:
        return
    try:
        sec = float(duration_sec)
    except Exception:
        return
    if sec < 0:
        return
    INGESTION_RUN_DURATION_SECONDS.labels(status=st, kind=k).observe(sec)


def adjust_processing_stage_gauge(
    *,
    prev_status: str | None,
    prev_stage: str | None,
    new_status: str | None,
    new_stage: str | None,
) -> None:
    """
    Best-effort gauge maintenance for "docs currently processing by stage".

    Call this only after the DB commit succeeds (or in a best-effort fire-and-forget manner).
    """
    if not _enabled():
        return

    p_status = _norm_status(prev_status)
    n_status = _norm_status(new_status)
    p_stage = _norm_stage(prev_stage)
    n_stage = _norm_stage(new_stage)

    was_processing = p_status == "processing"
    is_processing = n_status == "processing"

    if was_processing and is_processing:
        if p_stage != n_stage:
            INGESTION_PROCESSING_STAGE_TOTAL.labels(stage=p_stage).dec()
            INGESTION_PROCESSING_STAGE_TOTAL.labels(stage=n_stage).inc()
        return

    if was_processing and not is_processing:
        INGESTION_PROCESSING_STAGE_TOTAL.labels(stage=p_stage).dec()
        return

    if not was_processing and is_processing:
        INGESTION_PROCESSING_STAGE_TOTAL.labels(stage=n_stage).inc()


__all__ = [
    "INGESTION_RUNS_TOTAL",
    "INGESTION_RUN_DURATION_SECONDS",
    "INGESTION_PROCESSING_STAGE_TOTAL",
    "observe_ingestion_run_created",
    "observe_ingestion_run_finished",
    "adjust_processing_stage_gauge",
]

