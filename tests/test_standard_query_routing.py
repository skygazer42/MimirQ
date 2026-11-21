import pytest

from tests.test_standard_query_ownership import NoModuleCollaborators


def _runtime(query="Explain SSO", *, adaptive=None, **overrides):
    from app.api.schemas.conversations.chat import ChatRAGConfig
    from app.infrastructure.config import settings
    from app.rag.runtime.streaming.state import StandardStreamState

    payload = ChatRAGConfig(intent_router=False, **overrides).model_dump()
    payload["hierarchy_family_collapse"] = settings.HIERARCHY_RECALL_FAMILY_COLLAPSE
    return StandardStreamState(
        engine=NoModuleCollaborators(_route_retrieval_params=lambda score: {} if adaptive is None else adaptive),
        payload={
            **payload,
            "query_for_retrieval": query,
            "question": query,
            "complexity_score": 100.0,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "bucket", "mode", "weights"),
    [
        ("这个表结构有哪些字段", "schema", "keyword", (0.2, 0.8)),
        ("如何配置单点登录", "procedure", "hybrid", (0.7, 0.3)),
        ("2025年的增长率是多少", "numeric", "hybrid", (0.5, 0.5)),
        ("什么是单点登录", "definition", "keyword", (0.2, 0.8)),
    ],
)
async def test_stream_routing_retains_recall_buckets_without_engine_module(monkeypatch, query, bucket, mode, weights):
    from app.infrastructure.config import settings
    from app.rag.runtime.streaming import setup as standard_stream_setup

    monkeypatch.setattr(settings, "RAG_RECALL_BUCKETS_ENABLED", True)
    runtime = _runtime(query, retrieval_mode="auto")
    await standard_stream_setup.route_query(runtime)
    decision = runtime.data.query_routing_outcome
    assert runtime.data.recall_bucket == bucket and runtime.data.mode_auto is True
    assert runtime.data.mode_used == mode
    assert (runtime.data.vec_w, runtime.data.kw_w) == weights
    assert decision.normalization.retriever_update["retrieval_mode"] == mode


@pytest.mark.asyncio
async def test_stream_complexity_route_applies_after_profile_without_reapplying_it():
    from app.rag.runtime.streaming import setup as standard_stream_setup

    runtime = _runtime(
        retrieval_profile="recall50",
        adaptive={"top_k": 7, "retrieval_profile": "recall20", "enable_multi_query": False},
    )
    await standard_stream_setup.route_query(runtime)
    assert runtime.data.profile_norm == "recall20" and runtime.data.top_k == 7
    assert runtime.data.query_routing_outcome.normalization.retriever_update["k"] == 7
    assert runtime.data.query_routing_outcome.normalization.profile_applied["top_k"] == 50
    assert runtime.data.enable_multi_query is False


@pytest.mark.asyncio
async def test_stream_must_recall_keeps_its_strict_contract_when_default_is_blank(monkeypatch):
    from app.infrastructure.config import settings
    from app.rag.runtime.streaming import setup as standard_stream_setup

    monkeypatch.setattr(settings, "RETRIEVAL_CONTRACT_MODE", "")
    runtime = _runtime(must_recall=True)
    await standard_stream_setup.route_query(runtime)
    assert runtime.data.retrieval_contract_mode_effective == "must_recall_strict"
    assert runtime.data.retrieval_contract_policy["must_recall_strict"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("profile", "weight_rerank"), [("fast", False), ("recall50", True)])
async def test_stream_profile_controls_actual_weight_rerank_options(profile, weight_rerank):
    from app.rag.runtime.streaming import setup as standard_stream_setup

    runtime = _runtime(retrieval_profile=profile)
    await standard_stream_setup.route_query(runtime)
    update = runtime.data.query_routing_outcome.normalization.retriever_update
    assert update["enable_weight_rerank"] is weight_rerank
    assert runtime.data.weight_rerank is weight_rerank


def test_stream_rejects_the_retired_sparse_profile():
    with pytest.raises(ValueError, match="retired"):
        _runtime(retrieval_profile="sparse_splade")
