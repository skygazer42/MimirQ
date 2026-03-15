from __future__ import annotations

import pytest


def test_redis_rate_limiter_fail_open(monkeypatch):
    import app.api.middleware.rate_limit as rl

    class _BrokenClient:
        def eval(self, *_args, **_kwargs):  # noqa: ANN001
            raise RuntimeError("redis down")

    limiter = rl.RedisRateLimiter(redis_url="redis://localhost:6379/0", namespace="default")
    monkeypatch.setattr(limiter, "_get_client", lambda: _BrokenClient())

    allowed, wait_time = limiter.check("ip:127.0.0.1")

    assert allowed is True
    assert wait_time == pytest.approx(0.0)


def test_get_default_limiter_uses_redis_when_enabled(monkeypatch):
    import app.api.middleware.rate_limit as rl
    from app.core.config import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://localhost:6379/0", raising=False)
    monkeypatch.setattr(rl, "_default_limiter", None)

    limiter = rl.get_default_limiter()

    assert isinstance(limiter, rl.RedisRateLimiter)

