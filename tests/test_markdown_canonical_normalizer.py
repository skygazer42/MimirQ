from __future__ import annotations


def test_canonicalize_markdown_normalizes_key_structures() -> None:
    from app.rag.preprocessing.markdown_canonical import canonicalize_markdown

    raw = "##Heading\n*  item\n1)   first\n``` python  \n* not list\n```\na|b\n---|---\n1|2\n"

    out = canonicalize_markdown(raw)
    assert out.changed is True
    assert out.text == (
        "## Heading\n"
        "- item\n"
        "1. first\n"
        "```python\n"
        "* not list\n"
        "```\n"
        "| a | b |\n"
        "| --- | --- |\n"
        "| 1 | 2 |"
    )


def test_canonicalize_markdown_is_idempotent() -> None:
    from app.rag.preprocessing.markdown_canonical import canonicalize_markdown

    raw = "##Heading\n*  item\n1) first\n``` python\n* not list\n```\n"
    once = canonicalize_markdown(raw)
    twice = canonicalize_markdown(once.text)

    assert twice.text == once.text
    assert twice.changed is False

