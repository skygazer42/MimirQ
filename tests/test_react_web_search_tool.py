from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_react_workflow_registers_web_search_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.workflows.react as mod

    async def _fake_web_search(query: str, **kwargs):  # noqa: ANN001, ANN003
        return {
            "ok": True,
            "query": query,
            "provider": "serper",
            "providers_tried": ["serper"],
            "fallback_used": False,
            "total_results": 1,
            "results": [{"title": "Result", "url": "https://example.com", "snippet": "snippet", "source": "example.com"}],
            "errors": {},
            "kwargs": kwargs,
        }

    monkeypatch.setattr(mod, "web_search", _fake_web_search, raising=True)

    workflow = mod.ReActWorkflow(llm=object()).register_web_search_tool(
        provider_order=["serper", "brave"],
        max_results=4,
        site_filter=["docs.example.com"],
        lang="zh",
        region="cn",
    )

    assert "web_search" in workflow._tools
    result = await workflow._tools["web_search"].invoke("industrial gateway mqtt")
    assert "serper" in result
    assert "industrial gateway mqtt" in result
