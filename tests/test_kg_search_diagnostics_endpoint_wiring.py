import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1.evaluations import run_kg_search_diagnostics as kg_diag_endpoint
from app.core.config import settings
from app.core.database import get_db
from tests.helpers.async_utils import yield_control


class FakeDB:
    pass


def test_kg_search_diagnostics_endpoint_wires_runner(monkeypatch) -> None:
    app = FastAPI()
    app.post("/api/v1/evaluations/kg/search/diagnostics")(kg_diag_endpoint)

    app.dependency_overrides[get_db] = lambda: FakeDB()
    app.dependency_overrides[get_tenant_id] = lambda: uuid.uuid4()
    app.dependency_overrides[get_current_account_id] = lambda: "acct_123"

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)

    # Avoid dataset membership/ACL checks for this wiring test.
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_args, **_kwargs: None)

    # Stub the implementation to avoid real DB/KG/LLM work.
    import app.rag.evaluation.kg_search_diagnostics as impl_mod

    async def _stub_run(*_args, **_kwargs):
        await yield_control()
        ds_id = _kwargs.get("req").dataset_id
        return {
            "summary": {
                "dataset_id": str(ds_id),
                "cases_total": 0,
                "cases_evaluated": 0,
                "hardcases_generated": 0,
                "baseline_hit_rate": 0.0,
                "baseline_mrr": 0.0,
                "baseline_recall": 0.0,
                "failure_breakdown": {},
                "preflight": {},
            },
            "items": [],
        }

    monkeypatch.setattr(impl_mod, "run_kg_search_diagnostics", _stub_run)

    client = TestClient(app)
    res = client.post(
        "/api/v1/evaluations/kg/search/diagnostics",
        json={"dataset_id": str(uuid.uuid4()), "max_cases": 1, "k": 5},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "summary" in body
    assert body["items"] == []

