from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


def _override_get_current_account_id() -> str:
    return "test-account"


def test_dataset_analysis_glossary_writeback_endpoint_is_dataset_scoped(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.uuid4()
    captured: dict[str, object] = {}

    import app.api.v1.dataset_analysis as module

    class _Dataset:
        id = dataset_id
        name = "Dataset Glossary"

    monkeypatch.setattr(module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(module.DatasetService, "get_dataset", lambda *_a, **_k: _Dataset(), raising=True)

    def _fake_writeback(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {
            "schema": "mimirq.dataset_analysis.glossary_writeback.v1",
            "dataset_id": str(kwargs["dataset_id"]),
            "ruleset": kwargs["ruleset_name"],
            "candidate_count": 2,
            "added_count": 1,
            "skipped_count": 1,
            "added_tokens": ["MCU"],
            "skipped_tokens": ["485"],
        }

    monkeypatch.setattr(module, "writeback_dataset_analysis_glossary_candidates", _fake_writeback, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(module.router, prefix="/api/v1/datasets")
    client = TestClient(app)

    res = client.post(
        f"/api/v1/datasets/{dataset_id}/analysis/glossary-writeback",
        params={"ruleset": "industrial_control", "limit": 5, "feedback_polarity": "negative"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schema"] == "mimirq.dataset_analysis.glossary_writeback.v1"
    assert body["dataset_id"] == str(dataset_id)
    assert body["ruleset"] == "industrial_control"
    assert body["added_tokens"] == ["MCU"]
    assert captured["ruleset_name"] == "industrial_control"
    assert captured["limit"] == 5
    assert captured["feedback_polarity"] == "negative"
