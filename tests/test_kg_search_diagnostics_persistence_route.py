from __future__ import annotations

from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_kg_search_diagnostics_persist_run_sets_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.evaluations as eval_routes
    from app.api.schemas.kg_diagnostics import (
        KGSearchDiagnosticsRequest,
        KGSearchDiagnosticsResponse,
        KGSearchDiagnosticsSummary,
    )
    from app.core import config as config_mod
    from app.models.evaluation import KGSearchDiagnosticsRun
    from app.rag.evaluation import kg_search_diagnostics as diag_mod

    # Enable KG feature gate.
    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    # Avoid dataset service logic in this unit-style route test.
    monkeypatch.setattr(eval_routes.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(eval_routes.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(eval_routes.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    async def _fake_run_impl(*, db, tenant_id, account_id, req):  # noqa: ANN001
        # Return a minimal-but-valid diagnostics payload.
        await yield_control()
        summary = KGSearchDiagnosticsSummary(dataset_id=req.dataset_id, cases_total=0, cases_evaluated=0)
        return KGSearchDiagnosticsResponse(summary=summary, items=[])

    monkeypatch.setattr(diag_mod, "run_kg_search_diagnostics", _fake_run_impl, raising=True)

    db = _FakeSession()
    payload = KGSearchDiagnosticsRequest(dataset_id=UUID(int=1), max_cases=1, hardcase_mode="off", auto_extract_kg=False, persist_run=True)
    out = await eval_routes.run_kg_search_diagnostics(payload=payload, tenant_id=UUID(int=2), account_id="u", db=db)

    assert out.run_id is not None
    assert db.commits == 1
    run = next(obj for obj in db.added if isinstance(obj, KGSearchDiagnosticsRun))
    assert run.params.get("dataset_id") == str(payload.dataset_id)
    assert run.summary.get("dataset_id") == str(payload.dataset_id)
