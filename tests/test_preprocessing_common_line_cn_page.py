from app.rag.preprocessing.cleaning import build_repeated_line_signatures


def test_repeated_line_signatures_strip_cn_page_numbers():
    text = (
        "Company Confidential 第1页\n"
        "正文A\n"
        "Company Confidential 第2页\n"
        "正文B\n"
        "Company Confidential 第3页\n"
        "正文C\n"
    )
    sigs = build_repeated_line_signatures(text, min_occurrences=3)
    assert "company confidential" in sigs

