from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.core.regex_safety import RegexRulesValidationError, validate_regex_rules


def test_validate_regex_rules_rejects_too_many():  # noqa: ANN001
    with pytest.raises(RegexRulesValidationError) as excinfo:
        validate_regex_rules([{"pattern": "a"}] * 61)
    detail = excinfo.value.to_detail()
    assert detail["code"] == "regex_rules_invalid"
    assert any(e.get("code") == "too_many" for e in (detail.get("errors") or []))


def test_validate_regex_rules_rejects_suspicious_nested_quantifier():  # noqa: ANN001
    with pytest.raises(RegexRulesValidationError) as excinfo:
        validate_regex_rules([{"pattern": r"(.*)+", "repl": "", "flags": 0}])
    detail = excinfo.value.to_detail()
    assert any(e.get("code") == "unsafe" for e in (detail.get("errors") or []))


def test_pipeline_clean_preview_rejects_invalid_regex(monkeypatch):  # noqa: ANN001
    from app.api.v1.pipeline import clean_preview
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()

    class _DummyDB:
        def commit(self) -> None:
            return None

        def refresh(self, obj) -> None:  # noqa: ANN001
            return None

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/pipeline/clean-preview")(clean_preview)
    client = TestClient(app)

    res = client.post(
        "/api/v1/pipeline/clean-preview",
        json={
            "markdown": "hello",
            "rules": [{"pattern": "(", "repl": "", "flags": 0}],
            "use_default_rules": False,
        },
    )
    assert res.status_code == 400, res.text
    body = res.json()
    assert isinstance(body.get("detail"), dict)
    assert body["detail"].get("code") == "regex_rules_invalid"
    assert body["detail"].get("errors")

