from __future__ import annotations


def test_deepdoc_pdf_parser_preserves_page_order_when_ocr_runs_in_parallel() -> None:
    from app.deepdoc.parser.pdf_parser import IntegratedPipelinePdfParser

    parser = IntegratedPipelinePdfParser.__new__(IntegratedPipelinePdfParser)
    parser.boxes = [None, None, None]

    parser._store_ocr_boxes(2, [{"text": "page-3"}])
    parser._store_ocr_boxes(0, [{"text": "page-1"}])
    parser._store_ocr_boxes(1, [{"text": "page-2"}])

    assert [[box["text"] for box in page] for page in parser.boxes] == [
        ["page-1"],
        ["page-2"],
        ["page-3"],
    ]


def test_deepdoc_pdf_parser_keeps_serial_page_ocr_by_default(monkeypatch) -> None:
    from app.deepdoc.parser import pdf_parser

    monkeypatch.delenv("DEEPDOC_OCR_PAGE_CONCURRENCY", raising=False)

    assert pdf_parser._resolve_ocr_page_concurrency() == 1


def test_deepdoc_pdf_parser_respects_explicit_page_parallelism(monkeypatch) -> None:
    from app.deepdoc.parser import pdf_parser

    monkeypatch.setenv("DEEPDOC_OCR_PAGE_CONCURRENCY", "4")

    assert pdf_parser._resolve_ocr_page_concurrency() == 4
