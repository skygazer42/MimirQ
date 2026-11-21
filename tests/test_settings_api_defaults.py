import pytest


@pytest.mark.parametrize("model", [None, ""])
def test_dify_signature_preserves_zero_boost_budget_and_optional_model(model, monkeypatch):
    from app.api.v1.integrations import dify as module

    monkeypatch.setattr(module.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED", 0)
    monkeypatch.setattr(module.settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", False)
    monkeypatch.setattr(module.settings, "RERANKER_MODEL", model)
    signature = module._dify_response_cache_settings_signature()
    assert signature["kg_chunk_boost_max_promoted_default"] == 0
    assert signature["kg_chunk_boost_default"] is False
    assert signature["reranker_model"] == model


@pytest.mark.asyncio
async def test_zero_redirect_budget_disallows_all_redirect_hops(monkeypatch, tmp_path):
    from contextlib import asynccontextmanager

    import httpx
    from fastapi import HTTPException

    from app.api.utils import url_ingest

    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_MAX_REDIRECTS", 0)
    calls, closed = [], []
    response = httpx.Response(302, headers={"location": "/next"}, request=httpx.Request("GET", "https://example.test/"))

    class Client:
        @asynccontextmanager
        async def stream(self, *args, **kwargs):
            calls.append(args)
            try:
                yield response
            finally:
                closed.append("response")

    @asynccontextmanager
    async def client(**_kwargs):
        try:
            yield Client()
        finally:
            closed.append("client")

    async def unexpected_target(*_args, **_kwargs):
        pytest.fail("zero redirect budget attempted to follow a hop")

    monkeypatch.setattr(url_ingest.httpx, "AsyncClient", client)
    monkeypatch.setattr(url_ingest, "validate_fetch_target", unexpected_target)
    target = url_ingest.ValidatedFetchTarget(
        raw="https://example.test/",
        connect_url="https://93.184.216.34/",
        host="example.test",
        host_header="example.test",
    )
    with pytest.raises(HTTPException) as error:
        await url_ingest.download_url_to_path(
            target, tmp_path / "download", max_bytes=32, timeout_sec=1, follow_redirects=True
        )
    assert error.value.status_code == 400
    assert error.value.detail == "too many redirects"
    assert len(calls) == 1
    assert closed == ["response", "client"]


def test_scim_page_uses_configured_positive_cap(monkeypatch):
    from app.api.v1.identity import scim

    monkeypatch.setattr(scim.settings, "SCIM_PAGE_SIZE_MAX", 17)
    assert scim._scim_page(start_index=1, count=500)[1] == 17
