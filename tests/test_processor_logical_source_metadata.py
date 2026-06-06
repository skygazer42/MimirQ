from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from langchain_core.documents import Document


def test_attach_logical_source_metadata_prefers_upload_source_path(tmp_path: Path) -> None:
    from app.parsing.processors.processor import _attach_logical_source_metadata

    upload_path = tmp_path / "uuid.txt"
    db_document = SimpleNamespace(
        filename="招生.txt",
        doc_metadata={
            "source_path": "04专题常见问答/招生.txt",
            "user": {"source_rel_path": "ignored.txt"},
        },
    )
    docs = [
        Document(
            page_content="问题：招生怎么报名？\n答案：按通知办理。",
            metadata={"source": str(upload_path), "parser_backend": "text"},
        )
    ]

    out = _attach_logical_source_metadata(docs, db_document=db_document, file_path=upload_path)

    assert out[0].metadata["source"] == "04专题常见问答/招生.txt"
    assert out[0].metadata["source_path"] == "04专题常见问答/招生.txt"
    assert out[0].metadata["filename"] == "招生.txt"
    assert out[0].metadata["parser_source"] == str(upload_path)


def test_attach_logical_source_metadata_uses_user_source_rel_path_when_source_path_missing(tmp_path: Path) -> None:
    from app.parsing.processors.processor import _attach_logical_source_metadata

    upload_path = tmp_path / "uuid.txt"
    db_document = SimpleNamespace(
        filename="招生.txt",
        doc_metadata={"user": {"source_rel_path": "04专题常见问答/招生.txt"}},
    )

    out = _attach_logical_source_metadata(
        [Document(page_content="x", metadata={})],
        db_document=db_document,
        file_path=upload_path,
    )

    assert out[0].metadata["source"] == "04专题常见问答/招生.txt"
    assert out[0].metadata["source_path"] == "04专题常见问答/招生.txt"
