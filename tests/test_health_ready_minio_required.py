from __future__ import annotations

from fastapi import Response


class _DummyDB:
    def execute(self, _stmt):  # noqa: ANN001
        return None

    def close(self) -> None:
        return None


def test_ready_fails_when_minio_enabled_and_down(monkeypatch) -> None:
    import app.api.v1.health as health_mod

    monkeypatch.setattr(health_mod, "_ready_cache", {"ts": 0.0, "payload": None, "status": 200, "key": None})
    monkeypatch.setattr(health_mod, "SessionLocal", lambda: _DummyDB())
    monkeypatch.setattr(health_mod.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(health_mod.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(health_mod.settings, "EMBEDDING_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(health_mod.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(health_mod.settings, "MINIO_ENDPOINT", "localhost:9000", raising=False)
    monkeypatch.setattr(health_mod.milvus_store, "get_collection_count", lambda: 1)
    monkeypatch.setattr(
        health_mod.minio_service,
        "health_check",
        lambda: {"enabled": True, "status": "disconnected", "error": "minio down"},
    )

    response = Response()
    payload = health_mod.ready(response)

    assert response.status_code == 503
    assert payload["ok"] is False
    assert payload["minio"]["status"] == "disconnected"

