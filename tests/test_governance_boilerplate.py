from app.rag.preprocessing.boilerplate import remove_markdown_boilerplate


def test_remove_markdown_boilerplate_removes_sections_by_heading():
    md = (
        "# Title\n"
        "\n"
        "## 目录\n"
        "- 第一章 ...... 1\n"
        "- 第二章 ...... 2\n"
        "\n"
        "## 正文\n"
        "这里是内容。\n"
        "\n"
        "## 致谢\n"
        "感谢所有贡献者。\n"
        "\n"
        "## 附录\n"
        "保留这一节。\n"
    )
    res = remove_markdown_boilerplate(md)
    assert res.removed_sections == 2
    assert "## 目录" not in res.text
    assert "## 致谢" not in res.text
    assert "## 正文" in res.text
    assert "这里是内容" in res.text
    assert "## 附录" in res.text
    assert "保留这一节" in res.text


def test_remove_markdown_boilerplate_preserves_code_fences():
    md = (
        "```text\n"
        "## 目录\n"
        "```\n"
        "\n"
        "## 目录\n"
        "- item .... 1\n"
        "\n"
        "## Content\n"
        "keep\n"
    )
    res = remove_markdown_boilerplate(md)
    assert "```text\n## 目录\n```" in res.text
    assert res.text.count("## 目录") == 1
    assert "## Content" in res.text


def test_remove_markdown_boilerplate_removes_strong_footer_lines():
    md = "Hello\n\n版权所有 2024 某公司\n\nWorld\n"
    res = remove_markdown_boilerplate(md)
    assert "版权所有" not in res.text
    assert "Hello" in res.text
    assert "World" in res.text

