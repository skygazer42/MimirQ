import os

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize(
    "field,value",
    [
        ("TASK_JOB_TIMEOUT_SEC", 0),
        ("TASK_SEMAPHORE_LEASE_TTL_SEC", 0),
        ("SECURITY_HEADERS_HSTS_MAX_AGE_SEC", 0),
        ("TENANT_QPS_QUOTA_REDIS_KEY_TTL_SEC", 0),
        ("TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS", 0),
        ("UPLOAD_DIR", ""),
        ("TABLE_STORE_DIR", "   "),
    ],
)
def test_runtime_safety_settings_reject_invalid_values(field, value, monkeypatch):
    from app.core.config import Settings

    for key in list(os.environ):
        monkeypatch.delenv(key)
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, SECRET_KEY="unit-test-secret-key-with-more-than-32-characters", **{field: value})


def test_task_timeout_helpers_use_configured_values(monkeypatch):
    from app.tasks import locks

    monkeypatch.setattr(locks.settings, "TASK_JOB_TIMEOUT_SEC", 37)
    monkeypatch.setattr(locks.settings, "TASK_SEMAPHORE_LEASE_TTL_SEC", 19)
    assert locks.task_job_timeout_sec(default_sec=99) == 37
    assert locks.task_semaphore_lease_ttl_sec(default_sec=99) == 19
