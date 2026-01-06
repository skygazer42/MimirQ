from app.rag.preprocessing.cleaning import clean_markdown


def test_clean_markdown_removes_toc_lines_cn_and_en():
    md = (
        "目 录\n"
        "Chapter 1 .......... 1\n"
        "Section 2 …… 3\n"
        "\n"
        "# 正文\n"
        "这里是内容。\n"
    )
    res = clean_markdown(
        md,
        remove_toc_lines=True,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        trim_trailing_spaces=False,
        collapse_blank_lines=False,
    )
    assert "目 录" not in res.markdown
    assert "Chapter 1" not in res.markdown
    assert "Section 2" not in res.markdown
    assert "# 正文" in res.markdown


def test_clean_markdown_keeps_toc_lines_when_disabled():
    md = "目录\nChapter 1 .......... 1\n# Title\n"
    res = clean_markdown(
        md,
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        trim_trailing_spaces=False,
        collapse_blank_lines=False,
    )
    assert "目录" in res.markdown
    assert "Chapter 1" in res.markdown

