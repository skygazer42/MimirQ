import uuid

import starlette.status as _starlette_status
from fastapi import FastAPI
from fastapi.testclient import TestClient

if not hasattr(_starlette_status, "HTTP_413_CONTENT_TOO_LARGE"):
    _starlette_status.HTTP_413_CONTENT_TOO_LARGE = _starlette_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
if not hasattr(_starlette_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    _starlette_status.HTTP_422_UNPROCESSABLE_CONTENT = _starlette_status.HTTP_422_UNPROCESSABLE_ENTITY

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _build_app() -> tuple[FastAPI, object, object, object]:
    import app.main as main_module
    from app.api.v1 import health as health_module
    from app.api.v1 import meta as meta_module

    app = FastAPI()
    app.get("/health")(main_module.health_check)
    app.include_router(health_module.router, prefix="/api/v1")
    app.include_router(meta_module.router, prefix="/api/v1")
    return app, main_module, health_module, meta_module


def _reset_caches(health_module: object) -> None:
    health_module._ready_cache.update({"ts": 0.0, "payload": None, "status": 200, "key": None})  # type: ignore[attr-defined]
    health_module._redis_client = None  # type: ignore[attr-defined]


def test_public_health_endpoints_expose_only_minimal_status_fields(monkeypatch):  # noqa: ANN001
    app, _main_module, health_module, _meta_module = _build_app()
    _reset_caches(health_module)

    monkeypatch.setattr(health_module, "check_database", lambda *_args, **_kwargs: ({"status": "ok"}, True), raising=True)
    monkeypatch.setattr(
        health_module,
        "check_vector",
        lambda *_args, **_kwargs: ({"backend": "milvus", "status": "ok"}, {"status": "ok"}, True),
        raising=True,
    )
    monkeypatch.setattr(
        health_module,
        "check_redis",
        lambda *_args, **_kwargs: (
            {"status": "ok", "enabled": False, "required": False, "embedding_cache_enabled": False},
            True,
            False,
        ),
        raising=True,
    )
    monkeypatch.setattr(
        health_module,
        "check_minio",
        lambda *_args, **_kwargs: ({"status": "ok", "enabled": False}, True),
        raising=True,
    )

    client = TestClient(app)

    assert client.get("/health").json() == {"ok": True, "status": "healthy"}
    assert client.get("/api/v1/health").json() == {"ok": True, "status": "ok"}
    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"ok": True, "status": "ready"}


def test_public_ready_endpoint_preserves_probe_status_without_detail_leak(monkeypatch):  # noqa: ANN001
    app, _main_module, health_module, _meta_module = _build_app()
    _reset_caches(health_module)

    monkeypatch.setattr(health_module, "check_database", lambda *_args, **_kwargs: ({"status": "down"}, False), raising=True)
    monkeypatch.setattr(
        health_module,
        "check_vector",
        lambda *_args, **_kwargs: ({"backend": "milvus", "status": "ok"}, {"status": "ok"}, True),
        raising=True,
    )
    monkeypatch.setattr(
        health_module,
        "check_redis",
        lambda *_args, **_kwargs: (
            {"status": "ok", "enabled": False, "required": False, "embedding_cache_enabled": False},
            True,
            False,
        ),
        raising=True,
    )
    monkeypatch.setattr(
        health_module,
        "check_minio",
        lambda *_args, **_kwargs: ({"status": "ok", "enabled": False}, True),
        raising=True,
    )

    client = TestClient(app)
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"ok": False, "status": "unready"}


def test_health_details_are_admin_gated_and_expose_dependency_details(monkeypatch):  # noqa: ANN001
    app, _main_module, health_module, _meta_module = _build_app()
    _reset_caches(health_module)

    unauthenticated = TestClient(app).get("/api/v1/health/details")
    assert unauthenticated.status_code == 401

    monkeypatch.setattr(health_module, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(health_module, "check_database", lambda *_args, **_kwargs: ({"status": "ok"}, True), raising=True)
    monkeypatch.setattr(
        health_module,
        "check_vector",
        lambda *_args, **_kwargs: ({"backend": "milvus", "status": "ok"}, {"status": "ok"}, True),
        raising=True,
    )
    monkeypatch.setattr(
        health_module,
        "check_redis",
        lambda *_args, **_kwargs: (
            {"status": "ok", "enabled": False, "required": False, "embedding_cache_enabled": False},
            True,
            False,
        ),
        raising=True,
    )
    monkeypatch.setattr(
        health_module,
        "check_minio",
        lambda *_args, **_kwargs: ({"status": "ok", "enabled": False}, True),
        raising=True,
    )
    monkeypatch.setattr(health_module, "_get_redis_client", lambda: object(), raising=True)
    monkeypatch.setattr(health_module, "_ready_cache_key", lambda: ("test",), raising=True)
    monkeypatch.setattr(health_module, "_READY_CACHE_TTL_SEC", 0.0, raising=False)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: uuid.uuid4()
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"

    response = TestClient(app).get("/api/v1/health/details")

    assert response.status_code == 200
    assert response.json()["database"] == {"status": "ok"}
    assert response.json()["vector"] == {"backend": "milvus", "status": "ok"}
    assert "uploads" in response.json()


def test_public_meta_is_trimmed_and_details_are_admin_gated(monkeypatch):  # noqa: ANN001
    app, _main_module, _health_module, meta_module = _build_app()

    public = TestClient(app).get("/api/v1/meta")
    assert public.status_code == 200
    assert set(public.json().keys()) == {"name", "api_version", "build", "features"}
    assert set(public.json()["features"].keys()) == {"auth_mode"}

    unauthenticated = TestClient(app).get("/api/v1/meta/details")
    assert unauthenticated.status_code == 401

    monkeypatch.setattr(meta_module, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: uuid.uuid4()
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"

    detailed = TestClient(app).get("/api/v1/meta/details")

    assert detailed.status_code == 200
    assert "features" in detailed.json()
    assert "runtime" in detailed.json()


def test_health_and_meta_openapi_contracts_are_explicitly_typed() -> None:
    app, _main_module, _health_module, _meta_module = _build_app()
    paths = app.openapi()["paths"]

    expected_models = {
        "/api/v1/health": "HealthResponse",
        "/api/v1/health/ready": "ReadyResponse",
        "/api/v1/health/details": "HealthDetailsResponse",
        "/api/v1/meta": "MetaResponse",
        "/api/v1/meta/details": "MetaDetailsResponse",
    }
    for path, model in expected_models.items():
        schema = paths[path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith(f"/{model}")
