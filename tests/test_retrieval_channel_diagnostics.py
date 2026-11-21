from dataclasses import replace
from uuid import uuid4

import pytest

from app.infrastructure.config import settings
from app.rag.retrieval.configuration.options import HybridSearchOptions
from app.rag.retrieval.corpus import CorpusSearchResult
from app.rag.retrieval.ranking.candidates import FusionPolicy
from app.rag.retrieval.recall.channel_collection import (
    ChannelCollection,
    ChannelPlan,
    ChannelPolicy,
    ChannelRequest,
    KeywordRecall,
    VectorRecall,
)
from app.rag.retrieval.recall.channel_diagnostics import serialize_collected_channels
from app.rag.retrieval.recall.channel_health import RetrievalChannelHealth
from app.rag.retrieval.recall.lexical_search import LexicalOutcome
from app.rag.retrieval.recall.runtime_scope import ResolvedRetrievalScope, RetrievalScope
from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig


def _request(*, mode="hybrid", vector_filter=None):
    runtime = DatasetEmbeddingRuntimeConfig("openai_compatible", "fixture", "", "", "space", "documents", False)
    scope = ResolvedRetrievalScope(RetrievalScope(uuid4(), "actor"), (), (), runtime, None, None, vector_filter, False)
    return ChannelRequest("query", HybridSearchOptions(retrieval_mode=mode), scope)


def test_serialize_collected_channels_populates_counts_and_payloads(monkeypatch) -> None:
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    monkeypatch.setattr(settings, "LEXICAL_DB_FTS_CONFIG", "simple")
    monkeypatch.setattr(settings, "LEXICAL_DB_TRGM_ENABLED", True)
    keyword_strategy = {"primary": "lexical_db"}
    collection = ChannelCollection(
        ChannelPlan(True, True, True, keyword_strategy),
        VectorRecall(records=[{"score": 0.9}], elapsed_ms=12.345),
        KeywordRecall(
            bm25=CorpusSearchResult([{"score": 0.8}], {"ready": True}),
            lexical=LexicalOutcome(
                [
                    {"score": 0.7, "metadata": {"lexical_method": "fts"}},
                    {"score": 0.6, "metadata": {"lexical_method": "trgm"}},
                    {"score": 0.5, "metadata": {}},
                ],
                True,
            ),
            lexical_run_reason="hybrid_parallel",
            bm25_elapsed_ms=3.3,
            lexical_elapsed_ms=4.4,
        ),
        RetrievalChannelHealth(),
    )
    channels = replace(
        collection.channels, metadata_exact_pre_fusion_stats={"enabled": True, "annotated": 2, "promoted": 1}
    )

    channel_metrics = serialize_collected_channels(
        _request(vector_filter={"tenant_id": "fixture"}),
        collection,
        policy=ChannelPolicy(True, True, False, False, False, False, True),
        fusion=FusionPolicy("budgeted_rrf", 60, weights={"vector": 0.6, "bm25": 0.4}),
        channels=channels,
    )

    assert channel_metrics["timing"] == {
        "vector_ms": 12.35,
        "bm25_ms": 3.3,
        "lexical_ms": 4.4,
        "fusion_ms": 0.0,
    }
    assert channel_metrics["counts"] == {
        "vector_candidates": 1,
        "bm25_candidates": 1,
        "lexical_candidates": 3,
    }
    assert channel_metrics["vector"]["filter_applied"] is True
    assert channel_metrics["bm25"]["filter_applied"] is False
    assert channel_metrics["bm25"]["status"] == {"ready": True}
    assert channel_metrics["lexical_db"]["methods"] == {"fts": 1, "trgm": 1, "unknown": 1}
    assert channel_metrics["metadata_exact_pre_fusion"] == {"enabled": True, "annotated": 2, "promoted": 1}
    assert channel_metrics["fusion_weights"] == {"vector": 0.6, "bm25": 0.4}
    assert channel_metrics["keyword_strategy"] == {
        "primary": "lexical_db",
        "bm25_used": True,
        "lexical_db_used": True,
    }


@pytest.mark.parametrize("weights", [None, {}])
def test_serialize_collected_channels_omits_empty_fusion_weights(monkeypatch, weights) -> None:
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    collection = ChannelCollection(
        ChannelPlan(False, False, False, None), VectorRecall(), KeywordRecall(), RetrievalChannelHealth()
    )
    channel_metrics = serialize_collected_channels(
        _request(mode="keyword"),
        collection,
        policy=ChannelPolicy(False, False, False, True, False, False),
        fusion=FusionPolicy("weighted", 0, weights=weights),
        channels=collection.channels,
    )

    assert channel_metrics["fusion_weights"] is None
    assert channel_metrics["rrf_k"] == 0
    assert channel_metrics["vector"]["enabled"] is False
    assert channel_metrics["bm25"]["enabled"] is False
    assert channel_metrics["lexical_db"]["enabled"] is False
    assert channel_metrics["lexical_db"]["pg_trgm_available"] is None
    assert channel_metrics["all_retrieval_channels_failed"] is False
