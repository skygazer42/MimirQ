from app.rag.preprocessing.urls import canonicalize_url, normalize_urls


def test_canonicalize_url_strips_tracking_params():
    url = "https://example.com/path?a=1&utm_source=x&fbclid=abc#frag"
    out = canonicalize_url(url, strip_tracking=True)
    assert out == "https://example.com/path?a=1#frag"


def test_normalize_urls_rewrites_markdown_links_and_plain_urls():
    text = "Link [x](https://example.com?a=1&utm_medium=y). Also https://t.co/x?utm_campaign=z!"
    res = normalize_urls(text, strip_tracking=True)
    assert res.changed is True
    assert "[x](https://example.com?a=1)" in res.text
    assert "https://t.co/x" in res.text
    # Keeps trailing punctuation.
    assert res.text.endswith("!")

