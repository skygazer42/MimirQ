from app.rag.preprocessing.quality_filters import drop_if_low_density, drop_if_outline_only


def test_drop_if_outline_only_triggers_for_headings_and_lists():
    md = (
        "# Title\n"
        "## Section 1\n"
        "## Section 2\n"
        "- Item A\n"
        "- Item B\n"
        "- Item C\n"
    )
    decision = drop_if_outline_only(md, min_content_chars=200, max_heading_ratio=0.7)
    assert decision.dropped is True
    assert decision.reason == "outline_only"


def test_drop_if_outline_only_keeps_document_with_enough_content():
    md = "# Title\n\n" + ("This is real content. " * 30) + "\n"
    decision = drop_if_outline_only(md, min_content_chars=200, max_heading_ratio=0.85)
    assert decision.dropped is False


def test_drop_if_low_density_triggers_for_symbol_garbage():
    text = ("\u2026" * 200) + ("\n" + ("%" * 200)) * 5
    decision = drop_if_low_density(text, threshold=0.2)
    assert decision.dropped is True
    assert decision.reason == "low_density"


def test_drop_if_low_density_keeps_normal_text():
    text = ("Hello world 你好世界 " * 30).strip()
    decision = drop_if_low_density(text, threshold=0.2)
    assert decision.dropped is False

