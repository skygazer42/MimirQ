from __future__ import annotations

import contextlib
import uuid

import pytest


class _StubQuery:
    def __init__(self, *, first=None, all_rows=None):
        self._first = first
        self._all = list(all_rows or [])

    def filter(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        return self._first

    def all(self):  # noqa: ANN201
        return list(self._all)


class _StubDB:
    def __init__(self, *, document=None, chunks=None):
        self._document = document
        self._chunks = list(chunks or [])

    def query(self, model):  # noqa: ANN001, ANN201
        name = getattr(model, "__name__", "")
        if name == "Document":
            return _StubQuery(first=self._document)
        if name == "DocumentChunk":
            return _StubQuery(all_rows=self._chunks)
        raise AssertionError(f"unexpected model query: {name}")


class _Doc:
    def __init__(
        self,
        *,
        tenant_id: uuid.UUID,
        dataset_id: uuid.UUID,
        access_mode: str | None = None,
        owner_id: str | None = None,
        doc_metadata: dict | None = None,
        filename: str = "doc.txt",
        file_type: str = "txt",
    ):
        self.id = uuid.uuid4()
        self.tenant_id = tenant_id
        self.dataset_id = dataset_id
        self.disabled_at = None
        self.access_mode = access_mode
        self.owner_id = owner_id
        self.doc_metadata = doc_metadata or {}
        self.filename = filename
        self.file_type = file_type


class _Chunk:
    def __init__(self, *, chunk_index: int, content: str, page_number: int | None = None):
        self.id = uuid.uuid4()
        self.tenant_id = None
        self.document_id = None
        self.chunk_index = chunk_index
        self.content = content
        self.page_number = page_number
        self.disabled_at = None
        self.doc_metadata = {}


@pytest.mark.asyncio
async def test_get_document_content_requires_dataset_id():  # noqa: ANN001
    from app.rag.tools.mcp_tools import get_document_content

    res = await get_document_content(document_id=str(uuid.uuid4()), dataset_id=None)
    assert "dataset_id" in str(res.get("error") or "").lower()


@pytest.mark.asyncio
async def test_get_document_content_returns_joined_chunks(monkeypatch):  # noqa: ANN001
    import app.rag.tools.mcp_tools as tools_mod

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc = _Doc(tenant_id=tenant_id, dataset_id=dataset_id, doc_metadata={})
    chunks = [
        _Chunk(chunk_index=0, content="alpha", page_number=1),
        _Chunk(chunk_index=1, content="beta", page_number=1),
    ]

    @contextlib.contextmanager
    def _session():  # noqa: ANN001
        yield _StubDB(document=doc, chunks=chunks)

    monkeypatch.setattr(tools_mod, "_db_session", _session, raising=True)
    # Keep tenant scoping deterministic for this unit test.
    monkeypatch.setattr(tools_mod.settings, "DEFAULT_TENANT_ID", str(tenant_id), raising=False)

    res = await tools_mod.get_document_content(
        document_id=str(doc.id),
        dataset_id=str(dataset_id),
        max_chars=1000,
    )
    assert res.get("error") is None
    assert res.get("content") == "alpha\n\nbeta"
    assert res.get("chunk_count") == 2
    assert res.get("returned_chunks") == 2
    assert res.get("truncated") is False


@pytest.mark.asyncio
async def test_get_document_content_page_filter(monkeypatch):  # noqa: ANN001
    import app.rag.tools.mcp_tools as tools_mod

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc = _Doc(tenant_id=tenant_id, dataset_id=dataset_id, doc_metadata={})
    chunks = [
        _Chunk(chunk_index=0, content="p1-a", page_number=1),
        _Chunk(chunk_index=1, content="p2-a", page_number=2),
        _Chunk(chunk_index=2, content="p2-b", page_number=2),
    ]

    @contextlib.contextmanager
    def _session():  # noqa: ANN001
        yield _StubDB(document=doc, chunks=chunks)

    monkeypatch.setattr(tools_mod, "_db_session", _session, raising=True)
    monkeypatch.setattr(tools_mod.settings, "DEFAULT_TENANT_ID", str(tenant_id), raising=False)

    res = await tools_mod.get_document_content(
        document_id=str(doc.id),
        dataset_id=str(dataset_id),
        page=2,
        max_chars=1000,
    )
    assert res.get("error") is None
    assert res.get("content") == "p2-a\n\np2-b"
    assert res.get("pages") == [2]


@pytest.mark.asyncio
async def test_get_document_content_denies_only_me_for_non_owner(monkeypatch):  # noqa: ANN001
    import app.rag.tools.mcp_tools as tools_mod

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    doc = _Doc(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        access_mode="only_me",
        owner_id="alice",
        doc_metadata={},
    )

    @contextlib.contextmanager
    def _session():  # noqa: ANN001
        yield _StubDB(document=doc, chunks=[_Chunk(chunk_index=0, content="secret", page_number=1)])

    monkeypatch.setattr(tools_mod, "_db_session", _session, raising=True)
    monkeypatch.setattr(tools_mod.settings, "DEFAULT_TENANT_ID", str(tenant_id), raising=False)

    res = await tools_mod.get_document_content(
        document_id=str(doc.id),
        dataset_id=str(dataset_id),
        account_id="bob",
    )
    assert "access" in str(res.get("error") or "").lower()

