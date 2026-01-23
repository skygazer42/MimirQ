from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException


class _FakeQuery:
    def __init__(self, *, first=None, count_value: int | None = None, all_rows=None):  # noqa: ANN001
        self._first = first
        self._count = count_value
        self._all = all_rows

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def order_by(self, *_a, **_k):  # noqa: ANN001
        return self

    def with_entities(self, *_a, **_k):  # noqa: ANN001
        return self

    def limit(self, *_a, **_k):  # noqa: ANN001
        return self

    def count(self):  # noqa: ANN001
        return int(self._count or 0)

    def first(self):  # noqa: ANN001
        return self._first

    def all(self):  # noqa: ANN001
        return list(self._all or [])


class _FakeDB:
    def __init__(self, queries):  # noqa: ANN001
        self._queries = list(queries)

    def query(self, *_a, **_k):  # noqa: ANN001
        if not self._queries:
            raise AssertionError("Unexpected db.query call")
        return self._queries.pop(0)


@pytest.mark.asyncio
async def test_chunk_matches_document_not_found(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.documents import list_document_chunk_matches
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    db = _FakeDB([_FakeQuery(first=None)])
    with pytest.raises(HTTPException) as exc:
        await list_document_chunk_matches(
            document_id=UUID(int=1),
            q="hello",
            limit=10,
            tenant_id=UUID(int=1),
            account_id="u",
            db=db,
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_chunk_matches_blank_query_short_circuits(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.documents import list_document_chunk_matches
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    # Only one query() call is expected (document lookup). If the handler tries to
    # query chunks, _FakeDB will raise.
    doc = SimpleNamespace(dataset_id=None)
    db = _FakeDB([_FakeQuery(first=doc)])

    out = await list_document_chunk_matches(
        document_id=UUID(int=1),
        q="   ",
        limit=10,
        tenant_id=UUID(int=1),
        account_id="u",
        db=db,
    )
    assert out == {"total": 0, "truncated": False, "items": []}


@pytest.mark.asyncio
async def test_chunk_matches_returns_ids_and_truncation(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.documents import list_document_chunk_matches
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    doc = SimpleNamespace(dataset_id=None)
    rows = [(UUID(int=i), i, None) for i in range(5)]
    db = _FakeDB(
        [
            _FakeQuery(first=doc),  # document lookup
            _FakeQuery(count_value=6, all_rows=rows),  # chunk query
        ]
    )

    out = await list_document_chunk_matches(
        document_id=UUID(int=1),
        q="needle",
        limit=5,
        tenant_id=UUID(int=1),
        account_id="u",
        db=db,
    )
    assert out["total"] == 6
    assert out["truncated"] is True
    assert [item["chunk_index"] for item in out["items"]] == [0, 1, 2, 3, 4]
    assert out["items"][0]["id"] == str(UUID(int=0))


@pytest.mark.asyncio
async def test_chunk_matches_enforces_dataset_readable(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.documents import list_document_chunk_matches
    from app.services.dataset_service import DatasetService

    called: dict[str, object] = {}

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    def _fake_get_dataset(db, tenant_id, dataset_id):  # noqa: ANN001
        called["get_dataset"] = (db, tenant_id, dataset_id)
        return SimpleNamespace(id=dataset_id)

    def _fake_assert_dataset_readable(db, dataset, account_id):  # noqa: ANN001
        called["assert_readable"] = (db, dataset.id, account_id)
        return None

    monkeypatch.setattr(DatasetService, "get_dataset", _fake_get_dataset, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", _fake_assert_dataset_readable, raising=True)

    dataset_id = UUID(int=2)
    doc = SimpleNamespace(dataset_id=dataset_id)
    db = _FakeDB([_FakeQuery(first=doc), _FakeQuery(count_value=0, all_rows=[])])

    out = await list_document_chunk_matches(
        document_id=UUID(int=1),
        q="x",
        limit=10,
        tenant_id=UUID(int=1),
        account_id="u",
        db=db,
    )

    assert out["total"] == 0
    assert called["get_dataset"][2] == dataset_id
    assert called["assert_readable"][1] == dataset_id
