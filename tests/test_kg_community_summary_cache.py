from uuid import UUID

import pytest

from app.rag.kg.search import searcher as searcher_module
from app.rag.kg.search.cache import build_kg_community_summary_cache_key
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.searcher import KGSearcher


def test_kg_community_summary_cache_key_changes_with_scope() -> None:
    community_id = "community-1"
    query = "what changed"
    report = {"community_id": community_id, "summary": "same body"}

    key_a = build_kg_community_summary_cache_key(
        tenant_id=str(UUID(int=1)),
        dataset_id=str(UUID(int=2)),
        document_ids=[str(UUID(int=3))],
        community_id=community_id,
        query=query,
        report_payload=report,
    )
    key_b = build_kg_community_summary_cache_key(
        tenant_id=str(UUID(int=4)),
        dataset_id=str(UUID(int=2)),
        document_ids=[str(UUID(int=3))],
        community_id=community_id,
        query=query,
        report_payload=report,
    )
    key_c = build_kg_community_summary_cache_key(
        tenant_id=str(UUID(int=1)),
        dataset_id=str(UUID(int=5)),
        document_ids=[str(UUID(int=3))],
        community_id=community_id,
        query=query,
        report_payload=report,
    )
    key_d = build_kg_community_summary_cache_key(
        tenant_id=str(UUID(int=1)),
        dataset_id=str(UUID(int=2)),
        document_ids=[str(UUID(int=6))],
        community_id=community_id,
        query=query,
        report_payload=report,
    )

    assert len({key_a, key_b, key_c, key_d}) == 4


def test_kg_community_summary_cache_key_changes_with_report_content_fingerprint() -> None:
    scope = {
        "tenant_id": str(UUID(int=1)),
        "dataset_id": str(UUID(int=2)),
        "document_ids": [str(UUID(int=3))],
        "community_id": "community-1",
        "query": "what changed",
    }

    key_a = build_kg_community_summary_cache_key(
        **scope,
        report_payload={"community_id": "community-1", "summary": "version-a", "score": 0.7},
    )
    key_b = build_kg_community_summary_cache_key(
        **scope,
        report_payload={"community_id": "community-1", "summary": "version-b", "score": 0.7},
    )

    assert key_a != key_b


@pytest.mark.asyncio
async def test_lazy_community_summary_cache_key_uses_search_scope(monkeypatch) -> None:
    config = SearchConfig(
        query="what changed",
        tenant_id=UUID(int=1),
        dataset_id=UUID(int=2),
        document_ids=[UUID(int=3)],
    )
    captured_keys: list[str] = []

    monkeypatch.setattr(searcher_module.settings, "KG_LAZY_COMMUNITY_SUMMARY_ENABLED", True, raising=False)
    monkeypatch.setattr(searcher_module.settings, "KG_LAZY_COMMUNITY_SUMMARY_TOP_N", 1, raising=False)
    monkeypatch.setattr(searcher_module.settings, "KG_LAZY_COMMUNITY_SUMMARY_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(searcher_module.settings, "KG_LAZY_COMMUNITY_SUMMARY_CACHE_MAX_ENTRIES", 4, raising=False)

    def _cache_get(key: str, *, ttl_sec: int):
        assert ttl_sec == 60
        captured_keys.append(key)
        return "cached summary", 1

    monkeypatch.setattr(searcher_module.kg_community_summary_cache, "get", _cache_get)
    reports = [{"community_id": "community-1", "summary": "body"}]

    result = await KGSearcher.__new__(KGSearcher)._apply_lazy_community_summaries(
        config=config,
        reports=reports,
        query=config.query,
    )

    expected_key = build_kg_community_summary_cache_key(
        tenant_id=str(config.tenant_id),
        dataset_id=str(config.dataset_id),
        document_ids=[str(doc_id) for doc_id in config.document_ids or []],
        community_id="community-1",
        query=config.query,
        report_payload={"community_id": "community-1", "summary": "body"},
    )
    assert captured_keys == [expected_key]
    assert reports[0]["llm_summary"] == "cached summary"
    assert result["cache_hits"] == 1
