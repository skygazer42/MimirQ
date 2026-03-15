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

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def _build_client(monkeypatch):  # noqa: ANN001
    from app.api.v1.pipeline import clean_preview
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.post("/api/v1/pipeline/clean-preview")(clean_preview)
    return TestClient(app)


def test_pipeline_clean_preview_supports_rule_packs(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/pipeline/clean-preview",
        json={
            "markdown": "\n".join(
                [
                    "Cookie Consent",
                    "We use cookies to improve your experience on our site.",
                    "Accept cookies",
                    "",
                    "# Title",
                    "Real content stays.",
                ]
            ),
            "rule_packs": ["web_cookie_banners"],
            "use_default_rules": False,
            "include_diff": False,
            "remove_toc_lines": False,
            "remove_noise_lines": False,
            "unwrap_lines": False,
            "remove_common_lines": False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert "Cookie Consent" not in body["markdown"]
    assert "Real content stays." in body["markdown"]

    rule_stats = body.get("rule_stats") or []
    assert isinstance(rule_stats, list)
    hit_rules = [r for r in rule_stats if int(r.get("hits", 0) or 0) > 0]
    assert hit_rules
    assert all(r.get("source") == "pack" for r in hit_rules)
    assert any(r.get("pack") == "web_cookie_banners" for r in hit_rules)
