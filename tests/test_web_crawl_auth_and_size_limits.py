from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.utils import url_ingest
from app.api.v1 import connectors_web_crawl
from app.services import web_crawler


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_execute_web_crawl_run_passes_auth_headers_to_crawl_site(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeDB()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        config={
            "start_urls": ["https://example.com/start"],
            "auth": {"type": "bearer", "token": "top-secret"},
        },
        stats={},
        status="pending",
    )
    captured: dict[str, object] = {}

    async def fake_crawl_site(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return SimpleNamespace(urls=[], sync_tokens={})

    async def fake_process(**_kwargs):  # noqa: ANN003
        return {"created": 0, "failed": 0, "created_doc_ids": [], "source_manifest_state": {}}

    monkeypatch.setattr(connectors_web_crawl, "_get_web_crawl_run", lambda *args, **kwargs: run)
    monkeypatch.setattr(connectors_web_crawl, "_mark_web_crawl_run_running", lambda *args, **kwargs: None)
    monkeypatch.setattr(connectors_web_crawl, "_process_web_crawl_urls", fake_process)
    monkeypatch.setattr(connectors_web_crawl, "_web_crawl_run_cancelled", lambda *args, **kwargs: False)
    monkeypatch.setattr(connectors_web_crawl, "_finalize_web_crawl_run_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(connectors_web_crawl, "_mark_web_crawl_run_failed", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        connectors_web_crawl,
        "_leader_module",
        SimpleNamespace(
            SessionLocal=lambda: fake_db,
            decrypt_connector_config_secrets=lambda cfg: cfg,
            _normalize_connector_string_list=lambda value: list(value or []),
            _normalize_connector_principal_list=lambda value: list(value or []),
            _build_auth_headers=lambda cfg: {"Authorization": f"Bearer {cfg['auth']['token']}"},
            crawl_site=fake_crawl_site,
            _build_web_crawl_execution_plan=lambda **kwargs: {
                "crawl_urls": [],
                "discovered_urls": [],
                "delta_urls": [],
                "cursor_in": 0,
                "skipped_unchanged": 0,
                "removed_urls": [],
                "source_manifest_state": {},
                "discovered_manifest": {},
            },
            _initialize_web_crawl_run_stats=lambda **kwargs: {},
            _finalize_connector_stats=lambda stats: stats,
            _connector_run_completion_status=lambda **kwargs: "completed",
            _sync_connector_config_from_run=lambda **kwargs: None,
            _now=lambda: datetime.now(timezone.utc),
        ),
        raising=False,
    )

    await connectors_web_crawl._execute_web_crawl_run(
        run_id=run.id,
        tenant_id=run.tenant_id,
        requested_by="member-1",
    )

    assert captured["headers"] == {"Authorization": "Bearer top-secret"}
    assert fake_db.closed is True


@pytest.mark.asyncio
async def test_crawl_site_passes_headers_to_robots_and_sitemap_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    robots_headers: list[dict[str, str]] = []
    fetch_headers: list[tuple[str, dict[str, str]]] = []

    async def fake_validate(url: str) -> str:
        return url

    async def fake_load(self, *, base_url: str, headers: dict[str, str], timeout_sec: float, follow_redirects: bool):  # noqa: ANN001
        robots_headers.append(dict(headers))
        self._raw["example.com"] = "Sitemap: /secure-sitemap.xml"
        self._cache["example.com"] = None
        return None

    async def fake_fetch_page_text(
        url: str,
        *,
        headers: dict[str, str],
        timeout_sec: float,
        max_bytes: int,
        follow_redirects: bool,
    ) -> tuple[str, str, str]:
        fetch_headers.append((url, dict(headers)))
        assert timeout_sec > 0
        assert max_bytes > 0
        if url.endswith("sitemap.xml"):
            return (
                "<urlset><url><loc>https://example.com/secure-page</loc></url></urlset>",
                url,
                "application/xml",
            )
        raise AssertionError(f"unexpected fetch url: {url}")

    monkeypatch.setattr(web_crawler, "validate_url_for_ingest", fake_validate)
    monkeypatch.setattr(web_crawler._RobotsCache, "_load", fake_load)
    monkeypatch.setattr(web_crawler, "_fetch_page_text", fake_fetch_page_text)

    result = await web_crawler.crawl_site(
        start_urls=["https://example.com/start"],
        use_sitemaps=True,
        respect_robots=True,
        headers={"Authorization": "Bearer secret-token"},
        max_pages=5,
    )

    assert "https://example.com/secure-page" in result.urls
    assert robots_headers
    assert all(headers["Authorization"] == "Bearer secret-token" for headers in robots_headers)
    assert fetch_headers
    assert all(headers["Authorization"] == "Bearer secret-token" for _url, headers in fetch_headers)


@pytest.mark.asyncio
async def test_crawl_site_passes_headers_to_page_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    page_fetch_headers: list[dict[str, str]] = []

    async def fake_validate(url: str) -> str:
        return url

    async def fake_fetch_page_text(
        url: str,
        *,
        headers: dict[str, str],
        timeout_sec: float,
        max_bytes: int,
        follow_redirects: bool,
    ) -> tuple[str, str, str]:
        page_fetch_headers.append(dict(headers))
        return "<html><body>ok</body></html>", url, "text/html"

    monkeypatch.setattr(web_crawler, "validate_url_for_ingest", fake_validate)
    monkeypatch.setattr(web_crawler, "_fetch_page_text", fake_fetch_page_text)
    monkeypatch.setattr(web_crawler, "_extract_links_from_html", lambda html_text, *, base_url: ([], None))

    result = await web_crawler.crawl_site(
        start_urls=["https://example.com/start"],
        headers={"Authorization": "Bearer secret-token"},
        max_pages=1,
        max_depth=0,
        dedup_canonical=True,
    )

    assert result.urls == ["https://example.com/start"]
    assert page_fetch_headers == [{"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8", "User-Agent": "MimirQ/1.0 (+web-crawl)", "Authorization": "Bearer secret-token"}]
    assert result.sync_tokens["https://example.com/start"].startswith("content_type:text/html|body_sha256:")


@dataclass
class _FakeStreamResponse:
    status_code: int
    headers: dict[str, str]
    url: str
    chunks: list[bytes]

    async def __aenter__(self) -> "_FakeStreamResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk


class _FakeExternalClient:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    def stream(self, method: str, url: str, **kwargs):  # noqa: ANN001
        return self._response

    async def aclose(self) -> None:
        pass


class _FakeHTTPPool:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    async def get_external_client(self) -> _FakeExternalClient:
        return _FakeExternalClient(self._response)


class _RecordingExternalClient:
    def __init__(self, responses: list[_FakeStreamResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def stream(self, method: str, url: str, **kwargs):  # noqa: ANN001
        self.calls.append((url, dict(kwargs.get("headers") or {})))
        return self._responses.pop(0)

    async def aclose(self) -> None:
        pass


class _RecordingHTTPPool:
    def __init__(self, client: _RecordingExternalClient) -> None:
        self._client = client

    async def get_external_client(self) -> _RecordingExternalClient:
        return self._client


class _PinnedRecordingExternalClient:
    def __init__(self, responses: list[_FakeStreamResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def stream(self, method: str, url: str, **kwargs):  # noqa: ANN001
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(kwargs.get("headers") or {}),
                "extensions": dict(kwargs.get("extensions") or {}),
            }
        )
        return self._responses.pop(0)

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_fetch_page_text_raises_413_when_response_exceeds_max_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeStreamResponse(
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        url="https://example.com/large",
        chunks=[b"abcd", b"efgh"],
    )
    client = _FakeExternalClient(response)

    async def fake_target(url: str):  # noqa: ANN202
        assert url == "https://example.com/large"
        return url_ingest._ValidatedFetchTarget(
            raw="https://example.com/large",
            connect_url="https://93.184.216.34:443/large",
            host="example.com",
            host_header="example.com:443",
        )

    monkeypatch.setattr(web_crawler, "_validated_fetch_target", fake_target, raising=False)
    monkeypatch.setattr(web_crawler, "get_http_client_pool", lambda: _FakeHTTPPool(response))
    monkeypatch.setattr(web_crawler.httpx, "AsyncClient", lambda **_kwargs: client)

    with pytest.raises(HTTPException) as exc_info:
        await web_crawler._fetch_page_text(
            "https://example.com/large",
            headers={"Authorization": "Bearer secret-token"},
            timeout_sec=1.0,
            max_bytes=5,
            follow_redirects=False,
        )

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "remote file too large"


@pytest.mark.asyncio
async def test_fetch_page_text_strips_credentials_on_cross_origin_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingExternalClient(
        [
            _FakeStreamResponse(
                status_code=302,
                headers={"location": "https://evil.example/landing"},
                url="https://example.com/start",
                chunks=[],
            ),
            _FakeStreamResponse(
                status_code=200,
                headers={"content-type": "text/html"},
                url="https://evil.example/landing",
                chunks=[b"ok"],
            ),
        ]
    )

    async def fake_validate(url: str) -> str:
        return url

    async def fake_target(url: str):  # noqa: ANN202
        mapping = {
            "https://example.com/start": url_ingest._ValidatedFetchTarget(
                raw="https://example.com/start",
                connect_url="https://93.184.216.34:443/start",
                host="example.com",
                host_header="example.com:443",
            ),
            "https://evil.example/landing": url_ingest._ValidatedFetchTarget(
                raw="https://evil.example/landing",
                connect_url="https://203.0.113.10:443/landing",
                host="evil.example",
                host_header="evil.example:443",
            ),
        }
        return mapping[url]

    monkeypatch.setattr(web_crawler, "validate_url_for_ingest", fake_validate)
    monkeypatch.setattr(web_crawler, "_validated_fetch_target", fake_target, raising=False)
    monkeypatch.setattr(web_crawler, "get_http_client_pool", lambda: _RecordingHTTPPool(client))
    monkeypatch.setattr(web_crawler.httpx, "AsyncClient", lambda **_kwargs: client)

    await web_crawler._fetch_page_text(
        "https://example.com/start",
        headers={
            "Accept": "text/html",
            "Authorization": "Bearer secret-token",
            "Cookie": "session=secret",
        },
        timeout_sec=1.0,
        max_bytes=100,
        follow_redirects=True,
    )

    assert client.calls[0][1]["Authorization"] == "Bearer secret-token"
    assert client.calls[0][1]["Cookie"] == "session=secret"
    assert client.calls[1][1] == {"Accept": "text/html", "Host": "evil.example:443"}


@pytest.mark.asyncio
async def test_fetch_page_text_uses_pinned_connect_url_and_original_host_sni(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _PinnedRecordingExternalClient(
        [
            _FakeStreamResponse(
                status_code=200,
                headers={"content-type": "text/html"},
                url="https://93.184.216.34:443/start",
                chunks=[b"ok"],
            )
        ]
    )

    async def fake_target(url: str):  # noqa: ANN202
        assert url == "https://example.com/start"
        return url_ingest._ValidatedFetchTarget(
            raw="https://example.com/start",
            connect_url="https://93.184.216.34:443/start",
            host="example.com",
            host_header="example.com:443",
        )

    monkeypatch.setattr(web_crawler, "_validated_fetch_target", fake_target, raising=False)
    monkeypatch.setattr(web_crawler, "get_http_client_pool", lambda: _RecordingHTTPPool(client))
    monkeypatch.setattr(web_crawler.httpx, "AsyncClient", lambda **_kwargs: client)

    text, final_url, content_type = await web_crawler._fetch_page_text(
        "https://example.com/start",
        headers={"Accept": "text/html"},
        timeout_sec=1.0,
        max_bytes=100,
        follow_redirects=False,
    )

    assert text == "ok"
    assert final_url == "https://example.com/start"
    assert content_type == "text/html"
    assert client.calls == [
        {
            "method": "GET",
            "url": "https://93.184.216.34:443/start",
            "headers": {"Accept": "text/html", "Host": "example.com:443"},
            "extensions": {"sni_hostname": "example.com"},
        }
    ]


@pytest.mark.asyncio
async def test_fetch_page_text_revalidates_and_repins_redirect_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _PinnedRecordingExternalClient(
        [
            _FakeStreamResponse(
                status_code=302,
                headers={"location": "https://evil.example/landing"},
                url="https://93.184.216.34:443/start",
                chunks=[],
            ),
            _FakeStreamResponse(
                status_code=200,
                headers={"content-type": "text/html"},
                url="https://203.0.113.10:443/landing",
                chunks=[b"ok"],
            ),
        ]
    )

    async def fake_target(url: str):  # noqa: ANN202
        mapping = {
            "https://example.com/start": url_ingest._ValidatedFetchTarget(
                raw="https://example.com/start",
                connect_url="https://93.184.216.34:443/start",
                host="example.com",
                host_header="example.com:443",
            ),
            "https://evil.example/landing": url_ingest._ValidatedFetchTarget(
                raw="https://evil.example/landing",
                connect_url="https://203.0.113.10:443/landing",
                host="evil.example",
                host_header="evil.example:443",
            ),
        }
        return mapping[url]

    monkeypatch.setattr(web_crawler, "_validated_fetch_target", fake_target, raising=False)
    monkeypatch.setattr(web_crawler, "get_http_client_pool", lambda: _RecordingHTTPPool(client))
    monkeypatch.setattr(web_crawler.httpx, "AsyncClient", lambda **_kwargs: client)

    text, final_url, content_type = await web_crawler._fetch_page_text(
        "https://example.com/start",
        headers={
            "Accept": "text/html",
            "Authorization": "Bearer secret-token",
            "Cookie": "session=secret",
        },
        timeout_sec=1.0,
        max_bytes=100,
        follow_redirects=True,
    )

    assert text == "ok"
    assert final_url == "https://evil.example/landing"
    assert content_type == "text/html"
    assert client.calls == [
        {
            "method": "GET",
            "url": "https://93.184.216.34:443/start",
            "headers": {
                "Accept": "text/html",
                "Authorization": "Bearer secret-token",
                "Cookie": "session=secret",
                "Host": "example.com:443",
            },
            "extensions": {"sni_hostname": "example.com"},
        },
        {
            "method": "GET",
            "url": "https://203.0.113.10:443/landing",
            "headers": {"Accept": "text/html", "Host": "evil.example:443"},
            "extensions": {"sni_hostname": "evil.example"},
        },
    ]


@pytest.mark.asyncio
async def test_crawl_site_strips_credentials_from_off_origin_sitemap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched: list[tuple[str, dict[str, str]]] = []

    async def fake_validate(url: str) -> str:
        return url

    async def fake_fetch_page_text(
        url: str,
        *,
        headers: dict[str, str],
        timeout_sec: float,
        max_bytes: int,
        follow_redirects: bool,
    ) -> tuple[str, str, str]:
        fetched.append((url, dict(headers)))
        return (
            "<urlset><url><loc>https://example.com/page</loc></url></urlset>",
            url,
            "application/xml",
        )

    monkeypatch.setattr(web_crawler, "validate_url_for_ingest", fake_validate)
    monkeypatch.setattr(web_crawler, "_fetch_page_text", fake_fetch_page_text)

    result = await web_crawler.crawl_site(
        start_urls=["https://example.com/start"],
        sitemap_urls=["https://evil.example/sitemap.xml"],
        use_sitemaps=True,
        headers={"Authorization": "Bearer secret-token", "Cookie": "session=secret"},
        max_pages=1,
    )

    assert result.urls == ["https://example.com/page"]
    assert fetched[0][0] == "https://evil.example/sitemap.xml"
    assert "Authorization" not in fetched[0][1]
    assert "Cookie" not in fetched[0][1]


@pytest.mark.asyncio
async def test_crawl_site_oversized_page_falls_back_without_partial_body_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_validate(url: str) -> str:
        return url

    async def fake_fetch_page_text(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise HTTPException(status_code=413, detail="remote file too large")

    monkeypatch.setattr(web_crawler, "validate_url_for_ingest", fake_validate)
    monkeypatch.setattr(web_crawler, "_fetch_page_text", fake_fetch_page_text)

    result = await web_crawler.crawl_site(
        start_urls=["https://example.com/start"],
        max_pages=1,
        max_depth=0,
        dedup_canonical=True,
    )

    token = result.sync_tokens["https://example.com/start"]
    assert result.urls == ["https://example.com/start"]
    assert token.startswith("url_sha256:")
    assert "body_sha256" not in token
    assert result.errors
    assert result.errors[0]["url"] == "https://example.com/start"
