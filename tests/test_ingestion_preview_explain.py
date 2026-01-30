from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


def test_ingestion_preview_returns_explain_payload(monkeypatch):  # noqa: ANN001
    import app.api.v1.pipeline as pipeline_module
    from app.api.schemas.ingestion_policy import IngestionPolicy, IngestionRule
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _DummyDataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = tenant_id
            self.dataset_metadata = {}

    dummy_dataset = _DummyDataset()

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: dummy_dataset, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    rule = IngestionRule(id="r1", name="Rule 1", enabled=True)
    policy = IngestionPolicy(version="1", rules=[rule])

    monkeypatch.setattr(pipeline_module, "parse_ingestion_policy_from_metadata", lambda *_a, **_k: policy, raising=True)
    monkeypatch.setattr(pipeline_module, "match_ingestion_rule", lambda *_a, **_k: rule, raising=True)
    monkeypatch.setattr(pipeline_module, "resolve_pipeline_effective", lambda *_a, **_k: object(), raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        assert payload.get("action") == "pipeline_parse_preview"
        return {"backend": "basic", "pdf_quality": None, "markdown": "Hello", "images": []}

    async def _fake_clean_preview(*, body, tenant_id, account_id, db):  # noqa: ANN001, ANN202
        return {"markdown": body.markdown, "applied_rules": 0, "changed": False}

    monkeypatch.setattr(pipeline_module, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)
    monkeypatch.setattr(pipeline_module, "clean_preview", _fake_clean_preview, raising=True)

    class _DummyDB:
        pass

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/pipeline/ingestion-preview")(pipeline_module.ingestion_preview)
    client = TestClient(app)

    res = client.post(
        "/api/v1/pipeline/ingestion-preview",
        data={"dataset_id": str(dataset_id)},
        files={"file": ("demo.pdf", b"%PDF-1.4\\n%dummy\\n", "application/pdf")},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert "explain" in body
    assert isinstance(body["explain"], dict)
    assert body["explain"].get("rule")

