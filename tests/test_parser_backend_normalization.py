from app.parsing.backends import normalize_parser_backend


def test_normalize_parser_backend_magicpdf_aliases():
    assert normalize_parser_backend("magic-pdf") == "magicpdf"
    assert normalize_parser_backend("magic_pdf") == "magicpdf"
    assert normalize_parser_backend("magicpdf") == "magicpdf"


def test_normalize_parser_backend_basic_aliases():
    assert normalize_parser_backend("pymupdf") == "basic"
    assert normalize_parser_backend("fitz") == "basic"


def test_normalize_parser_backend_deepseek_ocr_aliases():
    assert normalize_parser_backend("deepseek-ocr") == "deepseek_ocr"
    assert normalize_parser_backend("deepseek_ocr") == "deepseek_ocr"
    assert normalize_parser_backend("deepseekocr") == "deepseek_ocr"


def test_normalize_parser_backend_etl4llm_aliases():
    assert normalize_parser_backend("etl4llm") == "etl4llm"
    assert normalize_parser_backend("etl-4llm") == "etl4llm"
    # Backward-compatible aliases (deprecated)
    assert normalize_parser_backend("bisheng-unstructured") == "etl4llm"
    assert normalize_parser_backend("bisheng_unstructured") == "etl4llm"
    assert normalize_parser_backend("bishengunstructured") == "etl4llm"
    assert normalize_parser_backend("bisheng") == "etl4llm"


def test_normalize_parser_backend_pandoc_aliases():
    assert normalize_parser_backend("pandoc") == "pandoc"
    assert normalize_parser_backend("pan-doc") == "pandoc"
    assert normalize_parser_backend("pan_doc") == "pandoc"


def test_normalize_parser_backend_empty():
    assert normalize_parser_backend(None) == ""
    assert normalize_parser_backend("") == ""
