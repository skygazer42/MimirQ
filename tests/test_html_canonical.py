import pytest


@pytest.mark.parametrize(
    ("html", "base_url", "expected"),
    [
        ("", "https://example.com/a", None),
        ("<html><head></head><body>hi</body></html>", "https://example.com/a", None),
        (
            "<link rel=\"canonical\" href=\"/post?id=1&utm_source=x#frag\">",
            "https://example.com/page",
            "https://example.com/post?id=1",
        ),
        (
            "<link rel='canonical nofollow' href='https://example.com/p?utm_campaign=y'>",
            "https://example.com/ignored",
            "https://example.com/p",
        ),
    ],
)
def test_extract_canonical_url(html: str, base_url: str, expected: str | None) -> None:
    from app.rag.preprocessing.html_canonical import extract_canonical_url

    assert extract_canonical_url(html, base_url=base_url) == expected

