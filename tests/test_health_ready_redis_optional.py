from __future__ import annotations

import sys
import types

from fastapi import Response


class _DummyDB:
    def execute(self, _stmt):
        return None

    def close(self) -> None:
        return None


def _install_failing_redis(monkeypatch, *, error: Exception) -> None:
    class _DummyRedisClient:
        def ping(self):
            raise error

    class _DummyRedis:
        @staticmethod
        def from_url(*_args, **_kwargs):
            return _DummyRedisClient()

    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=_DummyRedis))


def test_ready_does_not_fail_when_redis_only_for_cache(monkeypatch):
    import app.api.v1.health as health_mod

    monkeypatch.setattr(health_mod, "SessionLocal", lambda: _DummyDB())
    monkeypatch.setattr(health_mod.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(health_mod.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(health_mod.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(health_mod.settings, "EMBEDDING_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(health_mod.settings, "REDIS_URL", "redis://localhost:6379/0", raising=False)
    monkeypatch.setattr(health_mod.milvus_store, "get_collection_count", lambda: 1)

    _install_failing_redis(monkeypatch, error=RuntimeError("redis down"))

    response = Response()
    payload = health_mod.ready(response)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["redis"]["status"] == "disconnected"
    assert payload["redis"]["required"] is False


def test_ready_fails_when_task_queue_requires_redis(monkeypatch):
    import app.api.v1.health as health_mod

    monkeypatch.setattr(health_mod, "SessionLocal", lambda: _DummyDB())
    monkeypatch.setattr(health_mod.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(health_mod.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(health_mod.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(health_mod.settings, "EMBEDDING_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(health_mod.settings, "REDIS_URL", "redis://localhost:6379/0", raising=False)
    monkeypatch.setattr(health_mod.milvus_store, "get_collection_count", lambda: 1)

    _install_failing_redis(monkeypatch, error=RuntimeError("redis down"))

    response = Response()
    payload = health_mod.ready(response)

    assert response.status_code == 503
    assert payload["ok"] is False
    assert payload["redis"]["status"] == "disconnected"
    assert payload["redis"]["required"] is True

