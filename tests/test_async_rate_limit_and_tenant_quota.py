import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_redis_rate_limiter_acheck_offloads_sync_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.middleware.rate_limit import RedisRateLimiter

    limiter = RedisRateLimiter(redis_url="redis://example", namespace="tenant-qps")
    calls: list[tuple[object, tuple[object, ...]]] = []

    def fake_check(key: str) -> tuple[bool, float]:
        assert key == "tenant:key"
        return False, 1.25

    async def fake_to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls.append((func, args))
        return func(*args, **kwargs)

    monkeypatch.setattr(limiter, "check", fake_check)
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    allowed, retry_after = await limiter.acheck("tenant:key")

    assert (allowed, retry_after) == (False, 1.25)
    assert calls == [(fake_check, ("tenant:key",))]


@pytest.mark.asyncio
async def test_enforce_tenant_qps_quota_async_uses_async_limiter_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.tenant_quota_service as quota_service

    class _Limiter:
        def check(self, _key: str) -> tuple[bool, float]:
            raise AssertionError("sync limiter path should not run in async enforcement")

        async def acheck(self, key: str) -> tuple[bool, float]:
            assert key.endswith(":chat")
            return True, 0.0

    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_ENABLED", True, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_REQUESTS_PER_SECOND", 5.0, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_BURST_SIZE", 10, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_MODE", "block", raising=False)
    monkeypatch.setattr(quota_service, "_get_tenant_qps_limiter", lambda: _Limiter())

    meta = await quota_service.enforce_tenant_qps_quota_async(tenant_id=uuid4(), key="chat")

    assert meta["enabled"] is True
    assert meta["allowed"] is True


@pytest.mark.asyncio
async def test_enforce_tenant_qps_quota_async_raises_blocking_http_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.tenant_quota_service as quota_service

    class _Limiter:
        async def acheck(self, _key: str) -> tuple[bool, float]:
            return False, 1.2

    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_ENABLED", True, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_REQUESTS_PER_SECOND", 2.0, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_BURST_SIZE", 4, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_MODE", "block", raising=False)
    monkeypatch.setattr(quota_service, "_get_tenant_qps_limiter", lambda: _Limiter())

    with pytest.raises(HTTPException) as excinfo:
        await quota_service.enforce_tenant_qps_quota_async(tenant_id=uuid4(), key="retrieval")

    assert excinfo.value.status_code == 429
    assert excinfo.value.headers == {"Retry-After": "2"}
    assert excinfo.value.detail["scope"] == "tenant_qps:retrieval"


@pytest.mark.asyncio
async def test_enforce_tenant_qps_quota_async_degrades_open_on_backend_error_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.tenant_quota_service as quota_service

    metrics: list[dict[str, object]] = []
    tenant_id = uuid4()

    class _Limiter:
        async def acheck(self, _key: str) -> tuple[bool, float]:
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_ENABLED", True, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_REQUESTS_PER_SECOND", 2.0, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_BURST_SIZE", 4, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_MODE", "block", raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QUOTA_FAIL_CLOSED", False, raising=False)
    monkeypatch.setattr(quota_service, "_get_tenant_qps_limiter", lambda: _Limiter())
    monkeypatch.setattr(quota_service, "log_metrics", lambda payload: metrics.append(dict(payload)), raising=True)

    meta = await quota_service.enforce_tenant_qps_quota_async(tenant_id=tenant_id, key="retrieval")

    assert meta["enabled"] is False
    assert meta["allowed"] is True
    assert metrics == [
        {
            "event": "tenant_quota.guard",
            "tenant_id": str(tenant_id),
            "quota": "tenant_qps",
            "scope": "tenant_qps:retrieval",
            "outcome": "degraded",
            "reason": "tenant_quota_backend_unavailable",
            "backend": "redis",
            "error_type": "RuntimeError",
            "fail_closed": False,
        }
    ]


@pytest.mark.asyncio
async def test_enforce_tenant_qps_quota_async_fails_closed_on_backend_error_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.tenant_quota_service as quota_service

    metrics: list[dict[str, object]] = []

    class _Limiter:
        async def acheck(self, _key: str) -> tuple[bool, float]:
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_ENABLED", True, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_REQUESTS_PER_SECOND", 2.0, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_BURST_SIZE", 4, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QPS_QUOTA_MODE", "block", raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QUOTA_FAIL_CLOSED", True, raising=False)
    monkeypatch.setattr(quota_service, "_get_tenant_qps_limiter", lambda: _Limiter())
    monkeypatch.setattr(quota_service, "log_metrics", lambda payload: metrics.append(dict(payload)), raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await quota_service.enforce_tenant_qps_quota_async(tenant_id=uuid4(), key="retrieval")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "message": "Tenant quota enforcement unavailable",
        "retry_after_sec": None,
        "scope": "tenant_qps:retrieval",
        "reason": "tenant_quota_backend_unavailable",
    }
    assert metrics[0]["outcome"] == "closed"
    assert metrics[0]["fail_closed"] is True


def test_enforce_tenant_upload_quotas_degrades_open_on_db_fault_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.tenant_quota_service as quota_service

    metrics: list[dict[str, object]] = []
    audits: list[dict[str, object]] = []
    tenant_id = uuid4()

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def scalar(self) -> int:
            raise RuntimeError("db unavailable")

    class _DB:
        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return _Query()

    def _audit(_db, **kwargs):  # noqa: ANN001, ANN202
        audits.append(kwargs)

    monkeypatch.setattr(quota_service.settings, "TENANT_DOC_QUOTA_ENABLED", True, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_DOC_QUOTA_LIMIT", 3, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_STORAGE_QUOTA_ENABLED", False, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QUOTA_FAIL_CLOSED", False, raising=False)
    monkeypatch.setattr(quota_service, "log_metrics", lambda payload: metrics.append(dict(payload)), raising=True)
    monkeypatch.setattr(quota_service, "audit_log_event", _audit, raising=True)

    quota_service.enforce_tenant_upload_quotas(
        _DB(),  # type: ignore[arg-type]
        tenant_id=tenant_id,
        additional_docs=1,
        additional_bytes=128,
    )

    assert metrics == [
        {
            "event": "tenant_quota.guard",
            "tenant_id": str(tenant_id),
            "quota": "tenant_documents",
            "scope": "tenant_documents",
            "outcome": "degraded",
            "reason": "tenant_quota_backend_unavailable",
            "backend": "database",
            "error_type": "RuntimeError",
            "fail_closed": False,
            "additional_docs": 1,
            "additional_bytes": 128,
        }
    ]
    assert audits == [
        {
            "tenant_id": tenant_id,
            "actor_id": None,
            "action": "tenant_quota.guard",
            "resource_type": "tenant",
            "resource_id": str(tenant_id),
            "details": {
                "quota": "tenant_documents",
                "scope": "tenant_documents",
                "outcome": "degraded",
                "reason": "tenant_quota_backend_unavailable",
                "backend": "database",
                "error_type": "RuntimeError",
                "fail_closed": False,
                "additional_docs": 1,
                "additional_bytes": 128,
            },
        }
    ]


def test_enforce_tenant_upload_quotas_fails_closed_on_db_fault_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.tenant_quota_service as quota_service

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def scalar(self) -> int:
            raise RuntimeError("db unavailable")

    class _DB:
        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return _Query()

    monkeypatch.setattr(quota_service.settings, "TENANT_DOC_QUOTA_ENABLED", True, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_DOC_QUOTA_LIMIT", 3, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_STORAGE_QUOTA_ENABLED", False, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QUOTA_FAIL_CLOSED", True, raising=False)
    monkeypatch.setattr(quota_service, "log_metrics", lambda _payload: None, raising=True)
    monkeypatch.setattr(quota_service, "audit_log_event", lambda *_args, **_kwargs: None, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        quota_service.enforce_tenant_upload_quotas(
            _DB(),  # type: ignore[arg-type]
            tenant_id=uuid4(),
            additional_docs=1,
            additional_bytes=128,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "message": "Tenant quota enforcement unavailable",
        "retry_after_sec": None,
        "scope": "tenant_documents",
        "reason": "tenant_quota_backend_unavailable",
    }


def test_enforce_tenant_embedding_char_quota_fails_closed_on_db_fault_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.tenant_quota_service as quota_service

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def scalar(self) -> int:
            raise RuntimeError("db unavailable")

    class _DB:
        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return _Query()

    tenant_id = uuid4()
    metrics: list[dict[str, object]] = []
    audits: list[dict[str, object]] = []

    monkeypatch.setattr(quota_service.settings, "TENANT_EMBED_CHAR_QUOTA_ENABLED", True, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_EMBED_CHAR_QUOTA_LIMIT", 100, raising=False)
    monkeypatch.setattr(quota_service.settings, "TENANT_QUOTA_FAIL_CLOSED", True, raising=False)
    monkeypatch.setattr(quota_service, "log_metrics", lambda payload: metrics.append(dict(payload)), raising=True)
    monkeypatch.setattr(quota_service, "audit_log_event", lambda _db, **kwargs: audits.append(kwargs), raising=True)

    with pytest.raises(quota_service.TenantQuotaExceededError) as exc_info:
        quota_service.enforce_tenant_embedding_char_quota(
            _DB(),  # type: ignore[arg-type]
            tenant_id=tenant_id,
            additional_chars=321,
        )

    assert exc_info.value.quota == "embedding_chars_gate_unavailable"
    assert exc_info.value.meta == {
        "quota": "embedding_chars",
        "scope": "embedding_chars",
        "outcome": "closed",
        "reason": "tenant_quota_backend_unavailable",
        "backend": "database",
        "error_type": "RuntimeError",
        "fail_closed": True,
        "additional_chars": 321,
    }
    assert metrics == [
        {
            "event": "tenant_quota.guard",
            "tenant_id": str(tenant_id),
            "quota": "embedding_chars",
            "scope": "embedding_chars",
            "outcome": "closed",
            "reason": "tenant_quota_backend_unavailable",
            "backend": "database",
            "error_type": "RuntimeError",
            "fail_closed": True,
            "additional_chars": 321,
        }
    ]
    assert audits == [
        {
            "tenant_id": tenant_id,
            "actor_id": None,
            "action": "tenant_quota.guard",
            "resource_type": "tenant",
            "resource_id": str(tenant_id),
            "details": exc_info.value.meta,
        }
    ]
