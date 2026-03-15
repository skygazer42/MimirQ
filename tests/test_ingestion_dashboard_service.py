from __future__ import annotations

from datetime import UTC, datetime


def test_normalize_error_reason_is_stable_and_pii_safe() -> None:
    from app.services.ingestion_dashboard_service import _normalize_error_reason

    assert _normalize_error_reason(None) == "unknown"
    assert _normalize_error_reason("") == "unknown"

    # First line only + prefix before ":".
    assert _normalize_error_reason("FileNotFoundError: /tmp/a\nextra") == "FileNotFoundError"
    assert _normalize_error_reason("ValueError: bad input") == "ValueError"

    # ASCII sanitization (avoid paths/urls/payloads) + bounded length.
    assert _normalize_error_reason("permission denied: https://example.com/a?b=c") == "permission_denied"
    assert len(_normalize_error_reason("X:" + ("a" * 500))) <= 80


def test_build_throughput_timeseries_fills_missing_buckets_hourly() -> None:
    from app.services.ingestion_dashboard_service import _build_throughput_timeseries, _build_time_buckets

    since = datetime(2026, 1, 1, 10, 23, 0, tzinfo=UTC)
    now = datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC)
    buckets = _build_time_buckets(since=since, now=now, trunc_unit="hour")
    assert buckets == [
        datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    ]

    bucket_counts = {
        datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC): {"completed": 2},
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC): {"failed": 1, "quarantined": 3},
    }
    ts = _build_throughput_timeseries(buckets=buckets, bucket_counts=bucket_counts)
    assert ts["completed"] == [2, 0, 0]
    assert ts["failed"] == [0, 0, 1]
    assert ts["quarantined"] == [0, 0, 3]
    assert ts["cancelled"] == [0, 0, 0]


def test_build_time_buckets_daily_is_day_start() -> None:
    from app.services.ingestion_dashboard_service import _build_time_buckets

    since = datetime(2026, 1, 1, 10, 23, 0, tzinfo=UTC)
    now = datetime(2026, 1, 3, 0, 1, 0, tzinfo=UTC)
    buckets = _build_time_buckets(since=since, now=now, trunc_unit="day")
    assert buckets == [
        datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 3, 0, 0, 0, tzinfo=UTC),
    ]

