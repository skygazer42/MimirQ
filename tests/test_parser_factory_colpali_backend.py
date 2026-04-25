from __future__ import annotations


def test_normalize_parser_backend_colpali_aliases():
    from app.parsing.backends import normalize_parser_backend

    assert normalize_parser_backend("colpali") == "colpali"
    assert normalize_parser_backend("col-pali") == "colpali"
    assert normalize_parser_backend("col_qwen") == "colpali"


def test_parser_factory_routes_pdf_to_colpali_when_requested() -> None:
    from app.parsing.factory import ParserFactory

    backend = ParserFactory().resolve_backend(".pdf", "colpali")
    assert backend == "colpali"
