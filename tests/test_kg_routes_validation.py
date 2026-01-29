from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException


def test_resolve_allowed_documents_dedupes(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_API_MAX_DOCUMENT_IDS", 500, raising=False)

    called: dict[str, object] = {}

    def _fake_filter_allowed_document_ids(db, tenant_id, account_id, doc_ids):  # noqa: ANN001
        called["doc_ids"] = list(doc_ids)
        return list(doc_ids)

    monkeypatch.setattr(routes_mod, "filter_allowed_document_ids", _fake_filter_allowed_document_ids, raising=True)

    d1 = UUID(int=1)
    d2 = UUID(int=2)
    out = routes_mod._resolve_allowed_documents(
        document_ids=[d1, d1, d2],
        tenant_id=UUID(int=3),
        account_id="u",
        db=object(),
    )
    assert out == [d1, d2]
    assert called["doc_ids"] == [d1, d2]


def test_resolve_allowed_documents_rejects_too_many(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_API_MAX_DOCUMENT_IDS", 2, raising=False)

    monkeypatch.setattr(
        routes_mod,
        "filter_allowed_document_ids",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not be called")),
        raising=True,
    )

    doc_ids = [UUID(int=1), UUID(int=2), UUID(int=3)]
    with pytest.raises(HTTPException) as exc:
        routes_mod._resolve_allowed_documents(
            document_ids=doc_ids,
            tenant_id=UUID(int=3),
            account_id="u",
            db=object(),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_search_nodes_no_access_returns_empty(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import search_kg_graph_nodes
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [], raising=True)

    class _DB:
        def query(self, *_a, **_k):  # noqa: ANN001
            raise AssertionError("DB should not be queried when no docs are accessible")

    out = await search_kg_graph_nodes(
        q="hello",
        kind="all",
        limit=20,
        document_ids=None,
        tenant_id=UUID(int=1),
        account_id="u",
        db=_DB(),
    )
    assert out == []


@pytest.mark.asyncio
async def test_kg_search_tenant_mismatch(monkeypatch: pytest.MonkeyPatch):
    from app.core import config as config_mod
    from app.rag.kg.api.routes import run_kg_search
    from app.rag.kg.schemas import KGSearchRequest
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    payload = KGSearchRequest(query="q", tenant_id=UUID(int=1), document_ids=[UUID(int=2)])
    with pytest.raises(HTTPException) as exc:
        await run_kg_search(payload=payload, tenant_id=UUID(int=3), account_id="u", db=object())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_kg_search_timeout_returns_504(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import run_kg_search
    from app.rag.kg.schemas import KGSearchRequest
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(routes_mod, "_resolve_allowed_documents", lambda **_k: [UUID(int=2)], raising=True)

    async def _fake_kg_search(*_a, **_k):  # noqa: ANN001
        raise asyncio.TimeoutError("boom")

    monkeypatch.setattr(routes_mod, "kg_search", _fake_kg_search, raising=True)

    payload = KGSearchRequest(query="q", tenant_id=None, document_ids=[UUID(int=2)])
    with pytest.raises(HTTPException) as exc:
        await run_kg_search(payload=payload, tenant_id=UUID(int=1), account_id="u", db=object())
    assert exc.value.status_code == 504
