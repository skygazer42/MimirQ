from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.parametrize(
    ("schedule", "elapsed_sec", "expected"),
    [
        ("@hourly", 3599, False),
        ("@hourly", 3600, True),
        ("*/15 * * * *", 14 * 60, False),
        ("*/15 * * * *", 15 * 60, True),
        ("0 */6 * * *", 5 * 60 * 60 + 59, False),
        ("0 */6 * * *", 6 * 60 * 60, True),
        ("0 0 */2 * *", 2 * 24 * 60 * 60 - 1, False),
        ("0 0 */2 * *", 2 * 24 * 60 * 60, True),
    ],
)
def test_schedule_due(schedule: str, elapsed_sec: int, expected: bool) -> None:
    from app.api.v1.connectors import _schedule_due

    now = datetime(2026, 1, 31, 12, 0, 0, tzinfo=timezone.utc)
    last = now - timedelta(seconds=int(elapsed_sec))
    assert _schedule_due(schedule=schedule, now=now, last_run_at=last) is expected

