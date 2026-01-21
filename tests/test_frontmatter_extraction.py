from app.rag.preprocessing.frontmatter import extract_markdown_frontmatter, extract_markdown_title


def test_extract_markdown_frontmatter_parses_basic_fields():
    text = "\n".join(
        [
            "---",
            "title: My Doc",
            "tags: [a, b]",
            "author: 'Alice'",
            "date: 2025-01-01",
            "---",
            "",
            "# Hello",
            "Body",
        ]
    )
    res = extract_markdown_frontmatter(text, strip=False)
    assert res is not None
    assert res.data.get("title") == "My Doc"
    assert res.data.get("tags") == ["a", "b"]
    assert res.data.get("author") == "Alice"
    assert res.data.get("date") == "2025-01-01"
    assert res.changed is False


def test_extract_markdown_frontmatter_strip_removes_block():
    text = "\n".join(
        [
            "---",
            "title: My Doc",
            "---",
            "",
            "Body",
        ]
    )
    res = extract_markdown_frontmatter(text, strip=True)
    assert res is not None
    assert res.stripped_text == "Body"
    assert res.changed is True


def test_extract_markdown_frontmatter_multiline_list():
    text = "\n".join(
        [
            "---",
            "tags:",
            "  - a",
            "  - b",
            "---",
            "Body",
        ]
    )
    res = extract_markdown_frontmatter(text, strip=False)
    assert res is not None
    assert res.data.get("tags") == ["a", "b"]


def test_extract_markdown_title_prefers_h1_heading():
    text = "\n".join(
        [
            "```",
            "# Not a title inside code",
            "```",
            "",
            "# Real Title",
            "Body",
        ]
    )
    assert extract_markdown_title(text, max_lines=20) == "Real Title"

