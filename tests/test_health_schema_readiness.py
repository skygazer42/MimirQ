import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core import health_checks


def _session_local():  # noqa: ANN202
    engine = create_engine("sqlite+pysqlite:///:memory:")
    return engine, sessionmaker(bind=engine)


def test_database_readiness_allows_application_managed_schema_without_version_table() -> None:
    _engine, session_local = _session_local()

    status, ok = health_checks.check_database(session_local, require_schema_current=False)

    assert ok is True
    assert status == {"status": "connected"}


def test_database_readiness_fails_closed_when_managed_schema_version_is_missing(monkeypatch) -> None:
    _engine, session_local = _session_local()
    monkeypatch.setattr(health_checks, "_expected_alembic_heads", lambda: frozenset({"head"}))

    status, ok = health_checks.check_database(session_local, require_schema_current=True)

    assert ok is False
    assert status["status"] == "schema_outdated"
    assert status["schema_current"] is False
    assert status["expected_revisions"] == ["head"]


def test_database_readiness_requires_every_expected_alembic_head(monkeypatch) -> None:
    engine, session_local = _session_local()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('old')"))
    monkeypatch.setattr(health_checks, "_expected_alembic_heads", lambda: frozenset({"head"}))

    status, ok = health_checks.check_database(session_local, require_schema_current=True)

    assert ok is False
    assert status["status"] == "schema_outdated"
    assert status["current_revisions"] == ["old"]
    assert status["expected_revisions"] == ["head"]


def test_database_readiness_accepts_current_managed_schema(monkeypatch) -> None:
    engine, session_local = _session_local()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('head')"))
    monkeypatch.setattr(health_checks, "_expected_alembic_heads", lambda: frozenset({"head"}))

    status, ok = health_checks.check_database(session_local, require_schema_current=True)

    assert ok is True
    assert status == {
        "status": "connected",
        "schema_current": True,
        "current_revisions": ["head"],
        "expected_revisions": ["head"],
    }


def _build_ready_client() -> tuple[TestClient, object]:
    from app.api.v1 import health as health_module

    app = FastAPI()
    app.include_router(health_module.router, prefix="/api/v1")
    return TestClient(app), health_module


def _stub_ready_dependencies(monkeypatch: pytest.MonkeyPatch, health_module: object) -> None:
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
    monkeypatch.setattr(
        health_module,
        "get_rag_runtime_warmup_status",
        lambda: {"enabled": False, "status": "disabled", "ready": True},
        raising=True,
    )
    monkeypatch.setattr(health_module, "rag_runtime_warmup_ready", lambda: True, raising=True)
    monkeypatch.setattr(health_module, "minio_service", type("_Probe", (), {"is_enabled": lambda self: False})(), raising=True)


@pytest.mark.parametrize(
    ("create_all_on_startup", "runtime_migrations_enabled"),
    [(True, False), (False, True), (True, True)],
)
def test_ready_returns_200_when_application_manages_schema(
    monkeypatch: pytest.MonkeyPatch,
    create_all_on_startup: bool,
    runtime_migrations_enabled: bool,
) -> None:
    client, health_module = _build_ready_client()
    health_module.invalidate_ready_cache()
    _stub_ready_dependencies(monkeypatch, health_module)
    schema_requirements: list[bool] = []

    def _check_database(_session_local, *, require_schema_current: bool = False):  # noqa: ANN001, ANN202
        schema_requirements.append(require_schema_current)
        return {"status": "connected"}, True

    monkeypatch.setattr(health_module, "check_database", _check_database, raising=True)
    monkeypatch.setattr(health_module.settings, "DB_CREATE_ALL_ON_STARTUP", create_all_on_startup, raising=False)
    monkeypatch.setattr(
        health_module.settings,
        "DB_RUNTIME_MIGRATIONS_ENABLED",
        runtime_migrations_enabled,
        raising=False,
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "ready"}
    assert schema_requirements == [False]


def test_ready_returns_503_when_external_schema_is_outdated(monkeypatch: pytest.MonkeyPatch) -> None:
    client, health_module = _build_ready_client()
    health_module.invalidate_ready_cache()
    _stub_ready_dependencies(monkeypatch, health_module)
    schema_requirements: list[bool] = []

    def _check_database(_session_local, *, require_schema_current: bool = False):  # noqa: ANN001, ANN202
        schema_requirements.append(require_schema_current)
        return {"status": "schema_outdated", "schema_current": False}, False

    monkeypatch.setattr(health_module, "check_database", _check_database, raising=True)
    monkeypatch.setattr(health_module.settings, "DB_CREATE_ALL_ON_STARTUP", False, raising=False)
    monkeypatch.setattr(health_module.settings, "DB_RUNTIME_MIGRATIONS_ENABLED", False, raising=False)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"ok": False, "status": "unready"}
    assert schema_requirements == [True]


def test_ready_cache_is_busted_when_schema_management_flags_change(monkeypatch: pytest.MonkeyPatch) -> None:
    client, health_module = _build_ready_client()
    health_module.invalidate_ready_cache()
    _stub_ready_dependencies(monkeypatch, health_module)
    schema_requirements: list[bool] = []

    def _check_database(_session_local, *, require_schema_current: bool = False):  # noqa: ANN001, ANN202
        schema_requirements.append(require_schema_current)
        if require_schema_current:
            return {"status": "schema_outdated", "schema_current": False}, False
        return {"status": "connected"}, True

    monkeypatch.setattr(health_module, "check_database", _check_database, raising=True)
    monkeypatch.setattr(health_module, "_READY_CACHE_TTL_SEC", 60.0, raising=False)
    monkeypatch.setattr(health_module.settings, "DB_CREATE_ALL_ON_STARTUP", True, raising=False)
    monkeypatch.setattr(health_module.settings, "DB_RUNTIME_MIGRATIONS_ENABLED", False, raising=False)

    first_response = client.get("/api/v1/health/ready")

    monkeypatch.setattr(health_module.settings, "DB_CREATE_ALL_ON_STARTUP", False, raising=False)
    monkeypatch.setattr(health_module.settings, "DB_RUNTIME_MIGRATIONS_ENABLED", False, raising=False)

    second_response = client.get("/api/v1/health/ready")

    assert first_response.status_code == 200
    assert first_response.json() == {"ok": True, "status": "ready"}
    assert second_response.status_code == 503
    assert second_response.json() == {"ok": False, "status": "unready"}
    assert schema_requirements == [False, True]
