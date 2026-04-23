from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_web_search_falls_back_across_providers_and_returns_stable_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.tools.web_search as mod

    async def _fail_provider(**_kwargs):  # noqa: ANN003
        raise RuntimeError("provider down")

    async def _ok_provider(**_kwargs):  # noqa: ANN003
        return [
            {
                "title": "PLC Alarm Guide",
                "url": "https://example.com/plc",
                "snippet": "Guide for PLC alarm troubleshooting.",
                "source": "example.com",
            }
        ]

    monkeypatch.setattr(mod, "_run_tavily_search", _fail_provider, raising=True)
    monkeypatch.setattr(mod, "_run_serper_search", _ok_provider, raising=True)
    monkeypatch.setattr(mod, "_run_brave_search", _fail_provider, raising=True)

    out = await mod.web_search(
        "plc alarm troubleshooting",
        provider_order=["tavily", "serper", "brave"],
        max_results=3,
    )

    assert out["ok"] is True
    assert out["provider"] == "serper"
    assert out["fallback_used"] is True
    assert out["providers_tried"] == ["tavily", "serper"]
    assert out["total_results"] == 1
    assert out["results"][0]["title"] == "PLC Alarm Guide"
    assert out["results"][0]["url"] == "https://example.com/plc"


@pytest.mark.asyncio
async def test_web_search_passes_query_filters_to_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.tools.web_search as mod

    captured: dict = {}

    async def _capture_provider(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return []

    monkeypatch.setattr(mod, "_run_tavily_search", _capture_provider, raising=True)

    out = await mod.web_search(
        "industrial gateway mqtt",
        provider_order=["tavily"],
        max_results=5,
        site_filter=["docs.example.com", "kb.example.com"],
        freshness="30d",
        lang="zh",
        region="cn",
    )

    assert out["provider"] == "tavily"
    assert captured["query"] == "industrial gateway mqtt"
    assert captured["site_filter"] == ["docs.example.com", "kb.example.com"]
    assert captured["freshness"] == "30d"
    assert captured["lang"] == "zh"
    assert captured["region"] == "cn"
