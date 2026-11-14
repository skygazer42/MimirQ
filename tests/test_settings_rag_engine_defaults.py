import asyncio
from uuid import uuid4

import pytest


@pytest.mark.parametrize("complex_threshold,expected_profile", [(200.0, None), (0.0, "recall50")])
def test_zero_adaptive_threshold_is_not_replaced(complex_threshold, expected_profile, monkeypatch):
    from app.rag.engine_support.llm_routing import LlmRoutingMixin, settings

    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_SIMPLE_THRESHOLD", 0.0)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_COMPLEX_THRESHOLD", complex_threshold)
    result = LlmRoutingMixin._route_retrieval_params(None, 0.0)
    assert result.get("retrieval_profile") == expected_profile
    if expected_profile is None:
        assert result == {}


def test_kg_zero_concurrency_uses_existing_minimum(monkeypatch):
    from app.rag.kg import pipeline

    monkeypatch.setattr(pipeline.settings, "KG_SEARCH_MULTI_DATASET_MAX_CONCURRENCY", 0)
    observed = []

    async def shard(**kwargs):
        observed.append(kwargs["semaphore"]._value)
        return kwargs["scoped_dataset_id"], {}, None

    monkeypatch.setattr(pipeline, "_search_dataset_shard", shard)
    asyncio.run(
        pipeline._search_multi_dataset_scope(
            scoped_dataset_ids=[uuid4()], query="question", tenant_id=uuid4(), account_id="owner", query_mode=None
        )
    )
    assert observed == [1]
