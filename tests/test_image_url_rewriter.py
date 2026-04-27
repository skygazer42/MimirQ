from __future__ import annotations

from app.middleware.image_url_rewriter import rewrite_markdown_image_urls


def test_rewrite_markdown_image_urls_rewrites_markdown_and_html_refs() -> None:
    text = '![alt](images/a file.png)\\n<img src="images/b.png" alt="b">'
    mapping = {
        "images/a file.png": "https://cdn.local/a%20file.png",
        "images/b.png": "https://cdn.local/b.png",
    }

    out = rewrite_markdown_image_urls(text, mapping)

    assert "images/a file.png" not in out
    assert "images/b.png" not in out
    assert "https://cdn.local/a%20file.png" in out
    assert 'src="https://cdn.local/b.png"' in out


def test_rewrite_markdown_image_urls_keeps_unknown_refs_unchanged() -> None:
    text = "![alt](images/unknown.png)"

    out = rewrite_markdown_image_urls(text, {})

    assert out == text
