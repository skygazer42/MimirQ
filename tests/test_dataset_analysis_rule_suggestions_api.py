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


def test_dataset_analysis_rule_suggestions_endpoint_is_dataset_scoped(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.uuid4()
    captured: dict[str, object] = {}

    import app.api.v1.dataset_analysis as module

    class _Dataset:
        id = dataset_id
        name = "Dataset Rules"

    monkeypatch.setattr(module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(module.DatasetService, "get_dataset", lambda *_a, **_k: _Dataset(), raising=True)

    def _fake_build(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {
            "schema": "mimirq.industry_rules_suggestions.v1",
            "ruleset": kwargs["ruleset_name"],
            "glossary_suggestions": [{"token": "MCU"}],
            "pattern_suggestions": [{"pattern_key": "no_data"}],
            "intent_suggestions": [{"intent": "fault_troubleshooting"}],
        }

    monkeypatch.setattr(module, "build_dataset_analysis_rule_suggestions", _fake_build, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(module.router, prefix="/api/v1/datasets")
    client = TestClient(app)

    res = client.get(
        f"/api/v1/datasets/{dataset_id}/analysis/rule-suggestions",
        params={"ruleset": "industrial_control", "limit": 7},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schema"] == "mimirq.industry_rules_suggestions.v1"
    assert body["ruleset"] == "industrial_control"
    assert body["glossary_suggestions"] == [{"token": "MCU"}]
    assert captured["ruleset_name"] == "industrial_control"
    assert captured["limit"] == 7
