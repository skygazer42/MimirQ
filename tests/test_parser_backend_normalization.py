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


def test_normalize_parser_backend_bisheng_unstructured_aliases():
    assert normalize_parser_backend("bisheng-unstructured") == "bisheng_unstructured"
    assert normalize_parser_backend("bisheng_unstructured") == "bisheng_unstructured"
    assert normalize_parser_backend("bishengunstructured") == "bisheng_unstructured"
    assert normalize_parser_backend("bisheng") == "bisheng_unstructured"


def test_normalize_parser_backend_empty():
    assert normalize_parser_backend(None) == ""
    assert normalize_parser_backend("") == ""

