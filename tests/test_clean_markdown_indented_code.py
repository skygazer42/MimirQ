from app.rag.preprocessing.cleaning import clean_markdown


def test_clean_markdown_preserves_indented_code_blocks():
    md = (
        "Here is code:\n"
        "\n"
        "    x  =  1\n"
        "    def foo():\n"
        "        return  2\n"
        "\n"
        "End.\n"
    )
    res = clean_markdown(
        md,
        remove_noise_lines=False,
        remove_common_lines=False,
        remove_toc_lines=False,
        unwrap_lines=True,
    )
    assert "    x  =  1" in res.markdown
    assert "        return  2" in res.markdown

