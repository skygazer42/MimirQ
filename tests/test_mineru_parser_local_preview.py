from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.parsing.parsers.mineru_parser import MinerUParser


def test_mineru_parser_uses_local_service_for_preview_without_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%mineru-preview\n")

    monkeypatch.setattr(
        "app.parsing.parsers.mineru_parser.settings.MINERU_LOCAL_SERVER_URL",
        "http://mineru:8000",
        raising=False,
    )

    called: dict[str, object] = {}

    def _fake_parse_file_local(
        *,
        file_path: Path,
        dataset_id: str | None = None,
        document_id: str | None = None,
        tenant_id: str | None = None,
        params: dict | None = None,
    ) -> list[Document]:
        called.update(
            {
                "file_path": file_path,
                "dataset_id": dataset_id,
                "document_id": document_id,
                "tenant_id": tenant_id,
                "params": params,
            }
        )
        return [Document(page_content="mineru-local-preview", metadata={"parser_backend": "mineru"})]

    monkeypatch.setattr("app.parsing.parsers.mineru_parser.mineru_service.parse_file_local", _fake_parse_file_local)

    def _unexpected_super_parse(*_args, **_kwargs):
        raise AssertionError("MinerUParser should not fall back to BaseAdvancedParser.parse in local preview mode")

    monkeypatch.setattr("app.parsing.parsers.mineru_parser.BaseAdvancedParser.parse", _unexpected_super_parse)

    parser = MinerUParser()
    docs = parser.parse(pdf_path, tenant_id="tenant-preview")

    assert docs[0].page_content == "mineru-local-preview"
    assert called == {
        "file_path": pdf_path,
        "dataset_id": None,
        "document_id": None,
        "tenant_id": "tenant-preview",
        "params": None,
    }
