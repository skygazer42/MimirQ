from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException


class _FakeQuery:
    def __init__(self, result):  # noqa: ANN001
        self._result = result

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN001
        return self._result


class _FakeDB:
    def __init__(self, mapping):  # noqa: ANN001
        self._mapping = dict(mapping or {})

    def query(self, model):  # noqa: ANN001
        return _FakeQuery(self._mapping.get(model))


@pytest.mark.asyncio
async def test_documents_parsed_content_returns_available_and_truncates(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.documents import get_document_parsed_content
    from app.models.document import Document as DBDocument
    from app.models.document import DocumentParsedContent
    from app.services.dataset_service import DatasetService

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    dataset_id = UUID(int=3)

    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        doc_metadata={"parsed_content_persisted": {"enabled": True, "max_chars": 200_000}},
    )
    row = SimpleNamespace(
        tenant_id=tenant_id,
        document_id=document_id,
        markdown_content="a" * 50,
        original_markdown_content="b" * 60,
    )

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: None, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tenant_id, dataset_id: SimpleNamespace(id=dataset_id), raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda _db, _ds, _account_id: None, raising=True)

    db = _FakeDB({DBDocument: doc, DocumentParsedContent: row})

    out = await get_document_parsed_content(
        document_id=document_id,
        max_chars=40,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert out.available is True
    assert out.persisted_meta == {"enabled": True, "max_chars": 200_000}
    assert out.max_chars == 40

    assert out.markdown_content == "a" * 40
    assert out.markdown_truncated is True
    assert out.original_markdown_content == "b" * 40
    assert out.original_markdown_truncated is True


@pytest.mark.asyncio
async def test_documents_parsed_content_falls_back_to_local_text_source(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from app.api.v1 import document_content as content_module
    from app.models.document import Document as DBDocument
    from app.models.document import DocumentParsedContent
    from app.services.dataset_service import DatasetService

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    tenant_dir = tmp_path / str(tenant_id)
    tenant_dir.mkdir()
    source = tenant_dir / "sample.txt"
    source.write_text("hello txt cache fallback", encoding="utf-8")

    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        doc_metadata={},
        file_type="txt",
        filename="sample.txt",
        file_path=str(source),
    )

    monkeypatch.setattr(content_module.settings, "UPLOAD_DIR", str(tmp_path), raising=True)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: None, raising=True)

    db = _FakeDB({DBDocument: doc, DocumentParsedContent: None})
    out = await content_module.get_document_parsed_content(
        document_id=document_id,
        max_chars=10,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert out.available is True
    assert out.markdown_content == "hello txt "
    assert out.original_markdown_content == "hello txt "
    assert out.markdown_truncated is True
    assert out.original_markdown_truncated is True
    assert out.persisted_meta == {}


@pytest.mark.asyncio
async def test_documents_parsed_content_returns_unavailable_when_missing(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.documents import get_document_parsed_content
    from app.models.document import Document as DBDocument
    from app.models.document import DocumentParsedContent
    from app.services.dataset_service import DatasetService

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)

    doc = SimpleNamespace(id=document_id, tenant_id=tenant_id, dataset_id=None, doc_metadata={})

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: None, raising=True)

    db = _FakeDB({DBDocument: doc, DocumentParsedContent: None})
    out = await get_document_parsed_content(
        document_id=document_id,
        max_chars=200_000,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert out.available is False
    assert out.markdown_content == ""
    assert out.original_markdown_content == ""
    assert out.persisted_meta == {}


@pytest.mark.asyncio
async def test_documents_parsed_content_404_when_document_missing(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.documents import get_document_parsed_content
    from app.models.document import Document as DBDocument
    from app.services.dataset_service import DatasetService

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: None, raising=True)

    db = _FakeDB({DBDocument: None})

    with pytest.raises(HTTPException) as exc:
        await get_document_parsed_content(
            document_id=document_id,
            max_chars=200_000,
            tenant_id=tenant_id,
            account_id="u",
            db=db,
        )

    assert exc.value.status_code == 404
