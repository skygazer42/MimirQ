from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_crag_streaming_uses_web_fallback_when_retrieval_is_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.workflows.crag_streaming as mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "RAG_CRAG_STREAMING_ENABLED", True, raising=False)

    async def _fake_web_search(query: str, **_kwargs):  # noqa: ANN001, ANN003
        return {
            "ok": True,
            "query": query,
            "provider": "serper",
            "providers_tried": ["serper"],
            "fallback_used": False,
            "total_results": 1,
            "results": [
                {
                    "title": "PLC Alarm Guide",
                    "url": "https://example.com/plc",
                    "snippet": "Guide for PLC alarm troubleshooting.",
                    "source": "example.com",
                }
            ],
            "errors": {},
        }

    monkeypatch.setattr(mod, "web_search", _fake_web_search, raising=True)

    out = await mod.run_crag_streaming(
        question="How do I troubleshoot a PLC alarm?",
        retrieval_result={
            "citations": [],
            "metrics": {"top_relevance_score": 0.0},
            "abstain_triggered": True,
            "abstain_reason": "no_docs",
        },
        max_results=3,
    )

    assert out["used"] is True
    assert out["verdict"] == "incorrect"
    assert out["provider"] == "serper"
    assert out["web_result_count"] == 1
    assert "PLC Alarm Guide" in str(out["context_block"] or "")
    assert "https://example.com/plc" in str(out["context_block"] or "")
