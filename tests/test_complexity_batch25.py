
import datetime as dt
from datetime import timezone

import pytest


def _ensure_datetime_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dt, "UTC", timezone.utc, raising=False)


def test_semantic_sentence_chunker_preserves_numeric_runs_and_list_item_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_datetime_utc(monkeypatch)

    from langchain_core.documents import Document

    from app.rag.chunking.strategies.semantic import SemanticSentenceChunker

    text = (
        "Preface.\n"
        "- first item\n"
        "  continued detail\n"
        "- second item\n"
        "Version 1.2.3 stays together.\n"
    )
    chunker = SemanticSentenceChunker(chunk_size=25, chunk_overlap=0, min_chunk_size=0)

    chunks = chunker.split_documents([Document(page_content=text, metadata={})])

    assert [chunk.page_content for chunk in chunks] == [
        "Preface.",
        "- first item\n  continued detail\n",
        "- second item\n",
        "Version 1.2.3 stays together.",
    ]
    assert chunks[-1].metadata["chunk_strategy"] == "semantic_sentence"
    assert chunks[-1].metadata["start_char"] == text.index("Version 1.2.3")


def test_markdown_table_chunker_splits_only_on_row_boundaries_and_preserves_header_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_datetime_utc(monkeypatch)

    from langchain_core.documents import Document

    from app.rag.chunking.strategies.markdown_table import MarkdownTableChunker

    text = (
        "Lead in\n\n"
        "| Col A | Col B |\n"
        "| --- | --- |\n"
        "| alpha | one |\n"
        "| beta | two |\n"
        "| gamma | three |\n"
        "Tail text\n"
    )
    chunker = MarkdownTableChunker(chunk_size=52, chunk_overlap=0)

    chunks = chunker.split_documents([Document(page_content=text, metadata={"source": "table"})])
    table_chunks = [chunk for chunk in chunks if chunk.metadata.get("doc_type_kwd") == "table"]

    assert [chunk.page_content for chunk in table_chunks] == [
        "| Col A | Col B |\n| --- | --- |\n| alpha | one |\n",
        "| beta | two |\n| gamma | three |\n",
    ]
    assert table_chunks[0].metadata["table_header"] == "| Col A | Col B |\n| --- | --- |\n"
    assert table_chunks[0].metadata["table_row_start_index"] == 0
    assert table_chunks[0].metadata["table_row_end_index"] == 0
    assert table_chunks[1].metadata["table_row_start_index"] == 1
    assert table_chunks[1].metadata["table_row_end_index"] == 2
    assert table_chunks[0].metadata["table_start_char"] == table_chunks[1].metadata["table_start_char"]
    assert table_chunks[0].metadata["table_end_char"] == table_chunks[1].metadata["table_end_char"]


def test_parse_en_section_heading_accepts_dotted_numbers_without_decimal_false_positives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_datetime_utc(monkeypatch)

    from app.rag.chunking.strategies.laws_structured import _parse_en_section_heading

    assert _parse_en_section_heading("Section 12.3 Scope") == "12.3"
    assert _parse_en_section_heading("Section12.3 Scope") is None
    assert _parse_en_section_heading("Section 12.3.4a") is None


def test_laws_structured_chunker_preserves_heading_numbers_and_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_datetime_utc(monkeypatch)

    from langchain_core.documents import Document

    from app.rag.chunking.strategies.laws_structured import LawsStructuredChunker

    text = (
        "第1章 总则\n"
        "第1条 范围\n"
        "本法适用于测试场景，确保法规结构与编号语义不丢失。\n"
        "（一） 具体要求\n"
        "应当记录子项编号和完整层级路径。\n"
        "第2条 定义\n"
        "术语含义如下。\n"
    )
    chunker = LawsStructuredChunker(chunk_size=96, chunk_overlap=0)

    chunks = chunker.split_documents([Document(page_content=text, metadata={"source": "law"})])
    article_chunk = next(chunk for chunk in chunks if chunk.metadata.get("law_heading") == "第1条 范围")
    clause_chunk = next(chunk for chunk in chunks if chunk.metadata.get("law_heading") == "（一） 具体要求")

    assert article_chunk.metadata["law_kind"] == "article"
    assert article_chunk.metadata["law_number"] == "第1条"
    assert article_chunk.metadata["law_article"] == "第1条 范围"
    assert article_chunk.metadata["law_path"] == ["第1章 总则", "第1条 范围"]
    assert article_chunk.metadata["law_path_str"] == "第1章 总则 / 第1条 范围"
    assert clause_chunk.metadata["law_kind"] == "clause"
    assert clause_chunk.metadata["law_number"] == "（一）"
    assert clause_chunk.metadata["law_path"] == ["第1章 总则", "第1条 范围", "（一） 具体要求"]
    assert clause_chunk.metadata["law_path_str"] == "第1章 总则 / 第1条 范围 / （一） 具体要求"
