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


def test_dataset_analysis_summary_endpoint_is_dataset_scoped_and_emits_meta(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.uuid4()

    import app.api.v1.dataset_analysis as module

    class _Dataset:
        id = dataset_id
        name = "Dataset A"

    monkeypatch.setattr(module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(module.DatasetService, "get_dataset", lambda *_a, **_k: _Dataset(), raising=True)
    monkeypatch.setattr(
        module,
        "build_dataset_analysis_summary",
        lambda **kwargs: {
            "meta": {
                "filters": {
                    "dataset_id": str(kwargs["dataset_id"]),
                    "from_ts": kwargs["from_ts"],
                    "feedback_polarity": kwargs["feedback_polarity"],
                    "category": kwargs["category"],
                },
                "generated_at": "2026-04-22T12:00:00+00:00",
                "scope_summary": {"all_interactions": 20},
                "schema_version": "mimirq.dataset_analysis.summary.v1",
                "definitions": {"all_interactions": "all trace-backed interactions"},
            },
            "metrics": {"raw_positive_rate": 0.7},
            "counts": {"retrieval_miss": 2, "generation_error": 1, "out_of_scope": 1},
        },
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(module.router, prefix="/api/v1/datasets")
    client = TestClient(app)

    res = client.get(
        f"/api/v1/datasets/{dataset_id}/analysis/summary",
        params={
            "from_ts": "2026-04-01T00:00:00Z",
            "feedback_polarity": "negative",
            "category": "retrieval_miss",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["meta"]["filters"]["dataset_id"] == str(dataset_id)
    assert body["meta"]["filters"]["feedback_polarity"] == "negative"
    assert body["metrics"]["raw_positive_rate"] == 0.7


def test_dataset_analysis_examples_endpoint_supports_limit(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.uuid4()
    captured: dict[str, object] = {}

    import app.api.v1.dataset_analysis as module

    class _Dataset:
        id = dataset_id
        name = "Dataset B"

    monkeypatch.setattr(module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(module.DatasetService, "get_dataset", lambda *_a, **_k: _Dataset(), raising=True)

    def _fake_examples(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {
            "meta": {
                "filters": {"dataset_id": str(kwargs["dataset_id"]), "limit": kwargs["limit"], "category": kwargs["category"]},
                "generated_at": "2026-04-22T12:00:00+00:00",
                "scope_summary": {"feedback_interactions": 8},
                "schema_version": "mimirq.dataset_analysis.examples.v1",
                "definitions": {"top_examples": "ranked failure examples"},
            },
            "top_examples": [{"interaction_id": "req-1"}],
            "manual_review_candidates": [],
        }

    monkeypatch.setattr(module, "build_dataset_analysis_examples", _fake_examples, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(module.router, prefix="/api/v1/datasets")
    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/analysis/examples", params={"limit": 3, "category": "out_of_scope"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["top_examples"] == [{"interaction_id": "req-1"}]
    assert body["meta"]["filters"]["limit"] == 3
    assert captured["limit"] == 3
