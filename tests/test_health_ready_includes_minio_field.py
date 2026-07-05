from __future__ import annotations

from fastapi.testclient import TestClient


def test_ready_http_response_includes_minio(monkeypatch) -> None:
    import app.api.v1.health as health_mod
    from app.main import app

    # Force fresh computation (no cache hit).
    monkeypatch.setattr(health_mod, "_ready_cache", {"ts": 0.0, "payload": None, "status": 200, "key": None})

    # Avoid touching real infra in unit tests; we only verify the response shape.
    monkeypatch.setattr(health_mod, "check_database", lambda _session_local: ({"status": "connected"}, True))
    monkeypatch.setattr(
        health_mod,
        "check_vector",
        lambda *_args, **_kwargs: ({"backend": "milvus", "status": "connected"}, {}, True),
    )
    monkeypatch.setattr(
        health_mod,
        "check_redis",
        lambda *_args, **_kwargs: (
            {"status": "disabled", "enabled": False, "required": False, "embedding_cache_enabled": False},
            True,
            False,
        ),
    )
    monkeypatch.setattr(health_mod, "check_minio", lambda *_args, **_kwargs: ({"status": "disabled", "enabled": False}, True))

    monkeypatch.setattr(health_mod.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(health_mod.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(health_mod.settings, "EMBEDDING_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(health_mod.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(health_mod.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", False, raising=False)

    client = TestClient(app)
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["minio"]["status"] == "disabled"


def test_ready_http_response_reports_dify_warmup_status(monkeypatch) -> None:
    import app.api.v1.health as health_mod
    from app.main import app

    monkeypatch.setattr(health_mod, "_ready_cache", {"ts": 0.0, "payload": None, "status": 200, "key": None})
    monkeypatch.setattr(health_mod, "check_database", lambda _session_local: ({"status": "connected"}, True))
    monkeypatch.setattr(
        health_mod,
        "check_vector",
        lambda *_args, **_kwargs: ({"backend": "milvus", "status": "connected"}, {}, True),
    )
    monkeypatch.setattr(
        health_mod,
        "check_redis",
        lambda *_args, **_kwargs: (
            {"status": "disabled", "enabled": False, "required": False, "embedding_cache_enabled": False},
            True,
            False,
        ),
    )
    monkeypatch.setattr(health_mod, "check_minio", lambda *_args, **_kwargs: ({"status": "disabled", "enabled": False}, True))
    monkeypatch.setattr(health_mod.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(health_mod.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY", False, raising=False)

    import app.api.v1.integrations_dify as dify_api

    monkeypatch.setattr(
        dify_api,
        "get_dify_external_knowledge_warmup_status",
        lambda: {"enabled": True, "status": "running", "attempted": 8, "completed": 1, "failed": 0},
        raising=True,
    )
    monkeypatch.setattr(dify_api, "dify_external_knowledge_warmup_ready", lambda: False, raising=True)

    resp = TestClient(app).get("/api/v1/health/ready")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["dify_external_knowledge"]["status"] == "running"
    assert payload["dify_external_knowledge"]["ready"] is False
    assert payload["dify_external_knowledge"]["required_for_ready"] is False


def test_ready_http_response_can_require_dify_warmup(monkeypatch) -> None:
    import app.api.v1.health as health_mod
    from app.main import app

    monkeypatch.setattr(health_mod, "_ready_cache", {"ts": 0.0, "payload": None, "status": 200, "key": None})
    monkeypatch.setattr(health_mod, "check_database", lambda _session_local: ({"status": "connected"}, True))
    monkeypatch.setattr(
        health_mod,
        "check_vector",
        lambda *_args, **_kwargs: ({"backend": "milvus", "status": "connected"}, {}, True),
    )
    monkeypatch.setattr(
        health_mod,
        "check_redis",
        lambda *_args, **_kwargs: (
            {"status": "disabled", "enabled": False, "required": False, "embedding_cache_enabled": False},
            True,
            False,
        ),
    )
    monkeypatch.setattr(health_mod, "check_minio", lambda *_args, **_kwargs: ({"status": "disabled", "enabled": False}, True))
    monkeypatch.setattr(health_mod.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(health_mod.settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY", True, raising=False)

    import app.api.v1.integrations_dify as dify_api

    monkeypatch.setattr(
        dify_api,
        "get_dify_external_knowledge_warmup_status",
        lambda: {"enabled": True, "status": "running", "attempted": 8, "completed": 1, "failed": 0},
        raising=True,
    )
    monkeypatch.setattr(dify_api, "dify_external_knowledge_warmup_ready", lambda: False, raising=True)

    resp = TestClient(app).get("/api/v1/health/ready")

    assert resp.status_code == 503
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["dify_external_knowledge"]["required_for_ready"] is True
