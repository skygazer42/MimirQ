from __future__ import annotations

from pathlib import Path

from app.parsing.parsers.pdf_parser import PDFParser
from app.parsing.quality.reading_order import score_reading_order


def test_basic_pdf_parser_emits_chart_image_doc_for_image_only_pdf_page() -> None:
    parser = PDFParser()

    docs = parser.parse(Path("tests/fixtures/parsing_golden_broader/chart_pdf/input/sample.pdf"))

    assert len(docs) == 1
    assert docs[0].metadata["doc_type_kwd"] == "image"
    assert docs[0].metadata["visual_kind"] == "chart"
    assert docs[0].metadata["page"] == 1


def test_basic_pdf_parser_emits_line_chart_image_doc_for_image_only_pdf_page() -> None:
    parser = PDFParser()

    docs = parser.parse(Path("tests/fixtures/parsing_golden_broader/line_chart_pdf/input/sample.pdf"))

    assert len(docs) == 1
    assert docs[0].metadata["doc_type_kwd"] == "image"
    assert docs[0].metadata["visual_kind"] == "chart"
    assert docs[0].metadata["page"] == 1


def test_basic_pdf_parser_emits_diagram_image_doc_for_image_only_pdf_page() -> None:
    parser = PDFParser()

    docs = parser.parse(Path("tests/fixtures/parsing_golden_broader/diagram_pdf/input/sample.pdf"))

    assert len(docs) == 1
    assert docs[0].metadata["doc_type_kwd"] == "image"
    assert docs[0].metadata["visual_kind"] == "diagram"
    assert docs[0].metadata["page"] == 1


def test_basic_pdf_parser_tags_text_table_pdf_pages_as_table_documents() -> None:
    parser = PDFParser()

    docs = parser.parse(Path("tests/fixtures/parsing_golden_broader/merged_header_table_pdf/input/sample.pdf"))

    assert len(docs) == 1
    assert docs[0].metadata["doc_type_kwd"] == "table"
    assert docs[0].metadata["content_type"] == "table"
    assert docs[0].metadata["page"] == 1
    assert "Platform" in (docs[0].page_content or "")


def test_basic_pdf_parser_emits_position_tagged_text_for_two_column_pdf() -> None:
    parser = PDFParser()

    docs = parser.parse(Path("tests/fixtures/parsing_golden_broader/two_column_pdf/input/sample.pdf"))

    assert len(docs) == 1
    text = docs[0].page_content or ""
    assert "@@1\t" in text

    score = score_reading_order(text, min_blocks=2)

    assert score["score"] is not None
    assert float(score["score"]) > 0.8
    assert score["column_pages"] == 1


def test_basic_pdf_parser_marks_cross_page_table_continuation_metadata() -> None:
    parser = PDFParser()

    docs = parser.parse(Path("tests/fixtures/parsing_golden_broader/cross_page_table_pdf/input/sample.pdf"))

    assert len(docs) == 2
    assert docs[0].metadata["doc_type_kwd"] == "table"
    assert docs[0].metadata["table_truncated"] is True
    assert docs[1].metadata["doc_type_kwd"] == "table"
    assert docs[1].metadata["table_continued"] is True
    assert docs[1].metadata["table_columns"] == ["Region", "Q1", "Q2"]
