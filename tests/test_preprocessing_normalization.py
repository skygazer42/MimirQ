from app.rag.preprocessing.normalization import normalize_query, normalize_text


def test_normalize_text_removes_zero_width_and_soft_hyphen():
    raw = "a\u200b\u2060b\u00adc"
    assert normalize_text(raw) == "abc"


def test_normalize_text_expands_pdf_ligatures():
    assert normalize_text("of\ufb01ce") == "office"


def test_normalize_query_collapses_whitespace():
    assert normalize_query("  hello \n world \t ") == "hello world"

