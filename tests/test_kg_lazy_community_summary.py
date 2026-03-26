from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_searcher_lazy_summary_disabled_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.searcher as searcher_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_ENABLED", False, raising=False)

    async def _boom(*_args, **_kwargs):  # noqa: ANN001, ANN002
        raise AssertionError("LLM should not be called when lazy summary is disabled")

    monkeypatch.setattr(searcher_mod, "create_llm_client", _boom, raising=False)

    searcher = searcher_mod.KGSearcher()
    reports = [
        {"community_id": "1", "entities": [{"name": "A"}], "events": [{"title": "E1"}], "summary": "s1"},
        {"community_id": "2", "entities": [{"name": "B"}], "events": [{"title": "E2"}], "summary": "s2"},
    ]

    meta = await searcher._apply_lazy_community_summaries(reports=reports, query="q")

    assert meta["enabled"] is False
    assert meta["used"] is False
    assert "llm_summary" not in reports[0]
    assert "llm_summary" not in reports[1]


@pytest.mark.asyncio
async def test_searcher_lazy_summary_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.searcher as searcher_mod
    from app.core.config import settings
    from app.rag.kg.search.cache import kg_community_summary_cache
    from app.rag.llm.models import LLMResponse

    kg_community_summary_cache.clear()

    monkeypatch.setattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_TOP_N", 2, raising=False)
    monkeypatch.setattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_MAX_TOKENS", 180, raising=False)
    monkeypatch.setattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(settings, "KG_LAZY_COMMUNITY_SUMMARY_CACHE_MAX_ENTRIES", 16, raising=False)

    calls = {"chat": 0, "client": 0}

    class _FakeLLM:
        async def chat(self, messages, **_kwargs):  # noqa: ANN001, ANN003
            calls["chat"] += 1
            return LLMResponse(content=f"llm:{len(messages[0].content)}")

    async def _fake_create_llm_client(*_args, **_kwargs):  # noqa: ANN001, ANN002
        calls["client"] += 1
        return _FakeLLM()

    monkeypatch.setattr(searcher_mod, "create_llm_client", _fake_create_llm_client, raising=False)
    searcher = searcher_mod.KGSearcher()

    reports1 = [
        {"community_id": "1", "entities": [{"name": "A"}], "events": [{"title": "E1"}], "summary": "s1"},
        {"community_id": "2", "entities": [{"name": "B"}], "events": [{"title": "E2"}], "summary": "s2"},
        {"community_id": "3", "entities": [{"name": "C"}], "events": [{"title": "E3"}], "summary": "s3"},
    ]
    meta1 = await searcher._apply_lazy_community_summaries(reports=reports1, query="what happened")

    assert meta1["enabled"] is True
    assert meta1["used"] is True
    assert meta1["generated"] == 2
    assert meta1["cache_hits"] == 0
    assert "llm_summary" in reports1[0]
    assert "llm_summary" in reports1[1]
    assert "llm_summary" not in reports1[2]

    reports2 = [
        {"community_id": "1", "entities": [{"name": "A"}], "events": [{"title": "E1"}], "summary": "s1"},
        {"community_id": "2", "entities": [{"name": "B"}], "events": [{"title": "E2"}], "summary": "s2"},
        {"community_id": "3", "entities": [{"name": "C"}], "events": [{"title": "E3"}], "summary": "s3"},
    ]
    meta2 = await searcher._apply_lazy_community_summaries(reports=reports2, query="what happened")

    assert meta2["generated"] == 0
    assert meta2["cache_hits"] == 2
    assert calls["client"] == 1
    assert calls["chat"] == 2
    assert reports2[0]["llm_summary"] == reports1[0]["llm_summary"]
    assert reports2[1]["llm_summary"] == reports1[1]["llm_summary"]
