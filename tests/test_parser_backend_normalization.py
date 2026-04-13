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


def test_normalize_parser_backend_qianfan_ocr_aliases():
    assert normalize_parser_backend("qianfan-ocr") == "qianfan_ocr"
    assert normalize_parser_backend("qianfan_ocr") == "qianfan_ocr"
    assert normalize_parser_backend("qianfanocr") == "qianfan_ocr"


def test_normalize_parser_backend_textin_aliases():
    assert normalize_parser_backend("textin") == "textin"
    assert normalize_parser_backend("textin-xparse") == "textin"
    assert normalize_parser_backend("textin_xparse") == "textin"
    assert normalize_parser_backend("textinxparse") == "textin"


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


def test_normalize_parser_backend_marker_aliases():
    assert normalize_parser_backend("marker") == "marker"
    assert normalize_parser_backend("marker-pdf") == "marker"
    assert normalize_parser_backend("marker_pdf") == "marker"


def test_normalize_parser_backend_paddlevl_aliases():
    assert normalize_parser_backend("paddle_vl") == "paddle_vl"
    assert normalize_parser_backend("paddle-vl") == "paddle_vl"
    assert normalize_parser_backend("paddleocr-vl") == "paddle_vl"
    assert normalize_parser_backend("paddleocr_vl") == "paddle_vl"
    assert normalize_parser_backend("paddleocrvl") == "paddle_vl"


def test_normalize_parser_backend_glm_ocr_aliases():
    assert normalize_parser_backend("glm-ocr") == "glm_ocr"
    assert normalize_parser_backend("glm_ocr") == "glm_ocr"
    assert normalize_parser_backend("glmocr") == "glm_ocr"


def test_normalize_parser_backend_olmocr_aliases():
    assert normalize_parser_backend("olmocr") == "olmocr"
    assert normalize_parser_backend("olm-ocr") == "olmocr"
    assert normalize_parser_backend("olm_ocr") == "olmocr"
    assert normalize_parser_backend("olmocr-pdf") == "olmocr"
    assert normalize_parser_backend("olmocr_pdf") == "olmocr"


def test_normalize_parser_backend_empty():
    assert normalize_parser_backend(None) == ""
    assert normalize_parser_backend("") == ""
