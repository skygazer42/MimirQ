import pytest

from app.services.web_crawler import WebCrawlOptions
from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_web_crawl_records_missing_dependency_in_errors(monkeypatch):
    import app.services.web_crawler as mod

    async def fake_validate_url_for_ingest(url: str) -> str:
        await yield_control()
        return url

    async def fake_fetch_page_text(  # noqa: ANN202
        url: str,
        *,
        headers,
        timeout_sec,
        max_bytes,
        follow_redirects,
    ):
        await yield_control()
        return "<html><a href='http://example.com/a'>a</a></html>", url, "text/html"

    monkeypatch.setattr(mod, "validate_url_for_ingest", fake_validate_url_for_ingest)
    monkeypatch.setattr(mod, "_fetch_page_text", fake_fetch_page_text)
    monkeypatch.setattr(mod, "_get_lxml_html", lambda: None)

    res = await mod.crawl_site(
        options=WebCrawlOptions(
            start_urls=["http://example.com"],
            max_pages=1,
            max_depth=1,
            same_host_only=False,
            include_patterns=[],
            exclude_patterns=[],
        )
    )
    assert any(e.get("dependency") == "lxml" and e.get("reason") == "dependency_missing" for e in res.errors)
