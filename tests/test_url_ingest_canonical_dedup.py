from __future__ import annotations

import asyncio


def test_web_crawl_dedups_by_canonical(monkeypatch):  # noqa: ANN001
    import app.services.web_crawler as crawler

    async def _fake_validate(url: str) -> str:
        return url

    async def _fake_fetch_page_text(
        url: str,
        *,
        headers,  # noqa: ANN001
        timeout_sec,  # noqa: ANN001
        max_bytes,  # noqa: ANN001
        follow_redirects,  # noqa: ANN001
    ):
        if "page1" in url:
            html = '<html><head><link rel="canonical" href="https://example.com/canon"/></head><body>1</body></html>'
            return html, url, "text/html"
        if "page2" in url:
            html = '<html><head><link rel="canonical" href="https://example.com/canon"/></head><body>2</body></html>'
            return html, url, "text/html"
        return "<html></html>", url, "text/html"

    monkeypatch.setattr(crawler, "validate_url_for_ingest", _fake_validate, raising=True)
    monkeypatch.setattr(crawler, "_fetch_page_text", _fake_fetch_page_text, raising=True)
    monkeypatch.setattr(crawler, "_extract_links_from_html", lambda *_a, **_k: ([], None), raising=True)

    result = asyncio.run(
        crawler.crawl_site(
            start_urls=["https://example.com/page1", "https://example.com/page2"],
            max_pages=50,
            max_depth=1,
            same_host_only=True,
            include_patterns=[],
            exclude_patterns=[],
            respect_robots=False,
            dedup_canonical=True,
        )
    )

    assert result.urls == ["https://example.com/canon"]

