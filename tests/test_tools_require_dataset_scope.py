from __future__ import annotations

import asyncio
import uuid

import pytest


def test_search_knowledge_base_requires_dataset_id_when_no_document_ids(monkeypatch):  # noqa: ANN001
    import app.rag.tools.simple_kb_search as tools_mod

    # Ensure we don't accidentally call the real retriever.
    class _StubRetriever:
        def invoke(self, query):  # noqa: ANN001
            raise AssertionError("retriever.invoke should not be called for open-scope requests")

    class _StubHybrid:
        def model_copy(self, update=None, **_kw):  # noqa: ANN001
            return _StubRetriever()

    monkeypatch.setattr(tools_mod, "hybrid_retriever", _StubHybrid(), raising=True)

    out = tools_mod.search_knowledge_base(query="hi", top_k=3)
    assert "dataset_id" in out.lower()


def test_search_knowledge_base_passes_dataset_id_to_retriever(monkeypatch):  # noqa: ANN001
    import app.rag.tools.simple_kb_search as tools_mod

    captured: dict[str, object] = {}

    class _StubRetriever:
        def invoke(self, query):  # noqa: ANN001
            return []

    class _StubHybrid:
        def model_copy(self, update=None, **_kw):  # noqa: ANN001
            captured["update"] = update or {}
            return _StubRetriever()

    monkeypatch.setattr(tools_mod, "hybrid_retriever", _StubHybrid(), raising=True)

    ds = uuid.uuid4()
    out = tools_mod.search_knowledge_base(query="hi", top_k=3, dataset_id=str(ds))
    assert "no relevant documents" in out.lower()

    update = captured.get("update")
    assert isinstance(update, dict)
    assert str(update.get("dataset_id")) == str(ds)


@pytest.mark.asyncio
async def test_mcp_search_documents_requires_dataset_id(monkeypatch):  # noqa: ANN001
    import app.rag.retriever as retriever_mod

    # Ensure we don't accidentally call the real retriever.
    class _StubRetriever:
        async def ainvoke(self, query):  # noqa: ANN001
            await asyncio.sleep(0)  # Sonar S7503
            raise AssertionError("retriever.ainvoke should not be called for open-scope requests")

    class _StubHybrid:
        def model_copy(self, update=None, **_kw):  # noqa: ANN001
            return _StubRetriever()

    monkeypatch.setattr(retriever_mod, "hybrid_retriever", _StubHybrid(), raising=True)

    from app.rag.tools.mcp_tools import search_documents

    res = await search_documents(query="hello", top_k=3, dataset_id=None)
    assert res.get("count") == 0
    assert "dataset_id" in str(res.get("error") or "").lower()


@pytest.mark.asyncio
async def test_mcp_search_documents_passes_dataset_id_to_retriever(monkeypatch):  # noqa: ANN001
    import app.rag.retriever as retriever_mod

    captured: dict[str, object] = {}

    class _StubRetriever:
        async def ainvoke(self, query):  # noqa: ANN001
            await asyncio.sleep(0)  # Sonar S7503
            return []

    class _StubHybrid:
        def model_copy(self, update=None, **_kw):  # noqa: ANN001
            captured["update"] = update or {}
            return _StubRetriever()

    monkeypatch.setattr(retriever_mod, "hybrid_retriever", _StubHybrid(), raising=True)

    from app.rag.tools.mcp_tools import search_documents

    ds = uuid.uuid4()
    res = await search_documents(query="hello", top_k=3, dataset_id=str(ds))
    assert res.get("count") == 0

    update = captured.get("update")
    assert isinstance(update, dict)
    assert str(update.get("dataset_id")) == str(ds)
