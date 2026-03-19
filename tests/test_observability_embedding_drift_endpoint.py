from __future__ import annotations

import uuid

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


def test_observability_embedding_drift_snapshot_endpoint_calls_service(monkeypatch):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    import app.services.embedding_drift_monitor as drift_svc

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    assert hasattr(obs_mod, "get_embedding_drift_snapshot"), "Embedding drift snapshot endpoint not implemented yet"

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    called: dict[str, object] = {}

    def _fake_run_embedding_drift_monitor(**kwargs):  # noqa: ANN202
        called.update(kwargs)
        return {
            "schema": "mimirq.embedding_drift_snapshot.v1",
            "ok": True,
            "threshold": float(kwargs.get("drift_threshold") or 0.0),
            "sample_n_used": int(kwargs.get("sample_n") or 0),
            "stored_vectors_fetched": 1,
        }

    monkeypatch.setattr(drift_svc, "run_embedding_drift_monitor", _fake_run_embedding_drift_monitor, raising=True)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    from app.api.v1.observability import get_embedding_drift_snapshot

    app.get("/api/v1/observability/embedding-drift/snapshot")(get_embedding_drift_snapshot)
    client = TestClient(app)

    res = client.get(
        f"/api/v1/observability/embedding-drift/snapshot?dataset_id={dataset_id}&sample_n=12&drift_threshold=0.2"
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["schema"] == "mimirq.embedding_drift_snapshot.v1"
    assert body["sample_n_used"] == 12
    assert abs(float(body["threshold"]) - 0.2) < 1e-6

    assert str(called.get("tenant_id")) == str(tenant_id)
    assert str(called.get("dataset_id")) == str(dataset_id)
    assert called.get("sample_n") == 12
    assert abs(float(called.get("drift_threshold") or 0.0) - 0.2) < 1e-6

