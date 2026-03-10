from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _Config:
    def __init__(self, *, tenant_id: uuid.UUID, dataset_id: uuid.UUID, connector_id: str) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = tenant_id
        self.dataset_id = dataset_id
        self.connector_id = connector_id
        self.name = "cfg"
        self.enabled = True
        self.schedule_cron = None
        self.config = {"repo": "acme/docs"}
        self.state = {"source_manifest": {"docs/keep.md": "sha-1"}}


class _Doc:
    def __init__(self, *, connector_id: str, config_id: uuid.UUID, source_ref: str) -> None:
        self.id = uuid.uuid4()
        self.disabled_at = None
        self.doc_metadata = {
            "connector": {
                "connector_id": connector_id,
                "config_id": str(config_id),
                "source_ref": source_ref,
                "source_id": source_ref,
            }
        }


class _Query:
    def __init__(self, model, *, cfg: _Config, docs: list[_Doc]):  # noqa: ANN001
        self.model = model
        self._cfg = cfg
        self._docs = docs

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        name = getattr(self.model, "__name__", "")
        if name == "ConnectorConfig":
            return self._cfg
        return None

    def all(self):  # noqa: ANN201
        name = getattr(self.model, "__name__", "")
        if name == "Document":
            return list(self._docs)
        return []


class _DB:
    def __init__(self, *, cfg: _Config, docs: list[_Doc]) -> None:
        self.cfg = cfg
        self.docs = docs
        self.commits = 0

    def query(self, model):  # noqa: ANN001
        return _Query(model, cfg=self.cfg, docs=self.docs)

    def commit(self) -> None:
        self.commits += 1


def test_reconcile_connector_config_dry_run_returns_plan(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors_module

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    cfg = _Config(tenant_id=tenant_id, dataset_id=dataset_id, connector_id="github_repo")
    docs = [_Doc(connector_id="github_repo", config_id=cfg.id, source_ref="docs/stale.md")]
    db = _DB(cfg=cfg, docs=docs)

    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(connectors_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors_module, "audit_log_event", lambda *_a, **_k: None, raising=True)

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.include_router(connectors_module.router, prefix="/api/v1/connectors")
    client = TestClient(app)

    res = client.post(f"/api/v1/connectors/configs/{cfg.id}/reconcile?apply=false")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schema"] == "mimirq.connector_reconcile.v1"
    assert body["connector_id"] == "github_repo"
    assert body["stale_source_refs"] == 1
    assert body["stale_source_refs_sample"] == ["docs/stale.md"]
    assert body["missing_source_refs"] == 1
    assert body["missing_source_refs_sample"] == ["docs/keep.md"]
