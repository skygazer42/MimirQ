from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def commit(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def test_observability_deps_diagnostics_snapshot(monkeypatch):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_deps_diagnostics_snapshot

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    # Make the snapshot deterministic without hitting real deps.
    import app.services.deps_diagnostics_service as deps_mod

    monkeypatch.setattr(
        deps_mod,
        "_probe_postgres",
        lambda: {"status": "connected", "elapsed_ms": 12.3, "version": "15.2"},
        raising=True,
    )
    monkeypatch.setattr(
        deps_mod,
        "_probe_redis",
        lambda: {"status": "connected", "elapsed_ms": 3.2, "version": "7.2"},
        raising=True,
    )
    monkeypatch.setattr(
        deps_mod,
        "_probe_minio",
        lambda: {"status": "connected", "elapsed_ms": 8.8, "version": "client:7.2.0"},
        raising=True,
    )
    monkeypatch.setattr(
        deps_mod,
        "_probe_milvus",
        lambda: {"status": "connected", "elapsed_ms": 20.0, "version": "2.4.4"},
        raising=True,
    )

    tenant_id = uuid.uuid4()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/observability/diagnostics/deps")(get_deps_diagnostics_snapshot)
    client = TestClient(app)

    res = client.get("/api/v1/observability/diagnostics/deps")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body.get("schema") == "mimirq.observability.deps.v1"

    postgres = body.get("postgres") or {}
    assert postgres.get("status") == "connected"
    assert postgres.get("elapsed_ms") == pytest.approx(12.3)
    assert postgres.get("version") == "15.2"

    redis = body.get("redis") or {}
    assert redis.get("status") == "connected"
    assert redis.get("version") == "7.2"

    minio = body.get("minio") or {}
    assert minio.get("status") == "connected"
    assert minio.get("version") == "client:7.2.0"

    milvus = body.get("milvus") or {}
    assert milvus.get("status") == "connected"
    assert milvus.get("version") == "2.4.4"

