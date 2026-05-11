from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest


class _FakeQuery:
    def __init__(self, *, status_rows=None, sums=(0, 0)):  # noqa: ANN001
        self._status_rows = list(status_rows or [])
        self._sums = sums

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def with_entities(self, *_a, **_k):  # noqa: ANN001
        return self

    def group_by(self, *_a, **_k):  # noqa: ANN001
        return self

    def all(self):  # noqa: ANN001
        return list(self._status_rows)

    def one(self):  # noqa: ANN001
        return self._sums


class _FakeDB:
    def __init__(self, query):  # noqa: ANN001
        self._query = query

    def query(self, *_a, **_k):  # noqa: ANN001
        return self._query


@pytest.mark.asyncio
async def test_get_document_stats_dataset_scoped(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.document_stats import get_document_stats
    from app.services.dataset_service import DatasetService

    called: dict[str, object] = {}

    def _ensure_member(db, tenant_id, account_id):  # noqa: ANN001
        called["ensure_member"] = (tenant_id, account_id)
        return None

    def _get_dataset(db, tenant_id, dataset_id):  # noqa: ANN001
        called["get_dataset"] = (tenant_id, dataset_id)
        return SimpleNamespace(id=dataset_id)

    def _assert_dataset_readable(db, dataset, account_id):  # noqa: ANN001
        called["assert_dataset_readable"] = (dataset.id, account_id)
        return None

    monkeypatch.setattr(DatasetService, "ensure_member", _ensure_member, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", _get_dataset, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", _assert_dataset_readable, raising=True)

    q = _FakeQuery(
        status_rows=[("completed", 2), ("failed", 1), (None, 7)],
        sums=(10, 1234),
    )
    db = _FakeDB(q)

    tenant_id = UUID(int=1)
    dataset_id = UUID(int=2)

    out = await get_document_stats(
        dataset_id=dataset_id,
        q=None,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert out["total"] == 3
    assert out["by_status"] == {"completed": 2, "failed": 1}
    assert out["total_chunks"] == 10
    assert out["total_size"] == 1234

    assert called["ensure_member"] == (tenant_id, "u")
    assert called["get_dataset"] == (tenant_id, dataset_id)
    assert called["assert_dataset_readable"] == (dataset_id, "u")
