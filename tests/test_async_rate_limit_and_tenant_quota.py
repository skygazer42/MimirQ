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
