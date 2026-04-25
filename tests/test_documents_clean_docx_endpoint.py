from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from docx import Document as DocxDocument
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
async def test_download_document_clean_docx_builds_docx_from_parsed_markdown(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.documents import download_document_clean_docx
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
        filename="配置手册.docx",
        doc_metadata={},
    )
    parsed = SimpleNamespace(
        tenant_id=tenant_id,
        document_id=document_id,
        markdown_content="# 配置手册\n\n第一段\n\n第二段",
        original_markdown_content="",
    )

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: None, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tenant_id, dataset_id: SimpleNamespace(id=dataset_id), raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda _db, _ds, _account_id: None, raising=True)

    db = _FakeDB({DBDocument: doc, DocumentParsedContent: parsed})
    response = await download_document_clean_docx(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    body = b"".join([chunk async for chunk in response.body_iterator])
    loaded = DocxDocument(BytesIO(body))
    texts = [p.text for p in loaded.paragraphs if p.text.strip()]
    assert texts[0] == "配置手册"
    assert texts[1:] == ["第一段", "第二段"]
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in response.media_type


@pytest.mark.asyncio
async def test_download_document_clean_docx_404_when_parsed_content_missing(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.documents import download_document_clean_docx
    from app.models.document import Document as DBDocument
    from app.models.document import DocumentParsedContent
    from app.services.dataset_service import DatasetService

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)

    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        filename="配置手册.docx",
        doc_metadata={},
    )

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: None, raising=True)

    db = _FakeDB({DBDocument: doc, DocumentParsedContent: None})
    with pytest.raises(HTTPException) as exc:
        await download_document_clean_docx(
            document_id=document_id,
            tenant_id=tenant_id,
            account_id="u",
            db=db,
        )

    assert exc.value.status_code == 404
