from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest


class _FakeQuery:
    def __init__(self, *, run=None, runs=None) -> None:  # noqa: ANN001
        self._run = run
        self._runs = list(runs or [])

    def filter(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return self

    def order_by(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return self

    def limit(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return self

    def count(self) -> int:
        return int(len(self._runs))

    def all(self):  # noqa: ANN201
        return list(self._runs)

    def first(self):  # noqa: ANN201
        return self._run


class _FakeSession:
    def __init__(self, *, run=None, runs=None) -> None:  # noqa: ANN001
        self._run = run
        self._runs = list(runs or [])

    def query(self, model):  # noqa: ANN001
        name = getattr(model, "__name__", "")
        if name == "KGSearchDiagnosticsRun":
            return _FakeQuery(run=self._run, runs=self._runs)
        return _FakeQuery(run=None, runs=[])


@pytest.mark.asyncio
async def test_list_kg_search_diagnostics_runs_returns_total_and_items(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.evaluations as eval_routes
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(eval_routes.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(eval_routes.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(eval_routes.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    tenant_id = UUID(int=2)
    dataset_id = UUID(int=9)
    run = SimpleNamespace(
        id=UUID(int=1),
        tenant_id=tenant_id,
        account_id="u",
        dataset_id=dataset_id,
        status="completed",
        params={"x": 1},
        summary={"baseline_hit_rate": 0.5},
        created_at=datetime.now(UTC),
    )
    db = _FakeSession(runs=[run])

    out = await eval_routes.list_kg_search_diagnostics_runs(
        dataset_id=dataset_id, limit=20, tenant_id=tenant_id, account_id="u", db=db
    )
    assert out.total == 1
    assert len(out.items) == 1
    assert out.items[0].id == UUID(int=1)


@pytest.mark.asyncio
async def test_get_kg_search_diagnostics_run_returns_items(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.evaluations as eval_routes
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(eval_routes.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(eval_routes.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(eval_routes.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    tenant_id = UUID(int=2)
    dataset_id = UUID(int=9)
    items = [{"case_id": "c1", "attribution": {"primary_cause": "ok"}}]
    run = SimpleNamespace(
        id=UUID(int=1),
        tenant_id=tenant_id,
        account_id="u",
        dataset_id=dataset_id,
        status="completed",
        params={"x": 1},
        summary={"baseline_hit_rate": 0.5},
        items=items,
        created_at=datetime.now(UTC),
    )
    db = _FakeSession(run=run)

    out = await eval_routes.get_kg_search_diagnostics_run(
        run_id=UUID(int=1), tenant_id=tenant_id, account_id="u", db=db
    )
    assert out.run.id == UUID(int=1)
    assert out.items == items

