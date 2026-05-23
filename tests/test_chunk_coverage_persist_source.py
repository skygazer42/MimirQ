from __future__ import annotations

from pathlib import Path

from langchain_core.documents import Document

from app.parsing.processors.processor import _joined_text_total_characters


def test_joined_text_total_characters_matches_rebased_separator_model() -> None:
    docs = [
        Document(page_content="alpha"),
        Document(page_content="beta"),
        Document(page_content="gamma"),
    ]

    assert _joined_text_total_characters(docs, join_separator="\n\n") == len("alpha\n\nbeta\n\ngamma")
    assert _joined_text_total_characters(docs, join_separator="") == len("alphabetagamma")
    assert _joined_text_total_characters([], join_separator="\n\n") == 0


def test_processor_records_chunk_coverage_with_joined_text_total_before_indexing() -> None:
    source = Path("app/parsing/processors/processor.py").read_text(encoding="utf-8")

    assert "total_characters=_joined_text_total_characters(parsed_documents, join_separator=\"\\n\\n\")" in source
    assert "total_chars = int(total_characters or 0) or int(getattr(db_doc, \"total_characters\", 0) or 0)" in source
