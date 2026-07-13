
import time

import pytest
from langchain_core.documents import Document

from app.api.schemas.chat import ChatRAGConfig
from app.core.config import settings
from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides, is_recall_first_profile
from app.rag.retriever import HybridRetriever


def _mk_result(*, doc_id: str, chunk_index: int, score: float, content: str = "") -> dict:
    return {
        "chunk_id": f"{doc_id}:{chunk_index}",
        "content": content or f"chunk {doc_id}:{chunk_index}",
        "metadata": {"document_id": doc_id, "chunk_index": chunk_index, "chunk_id": f"{doc_id}:{chunk_index}"},
        "score": float(score),
    }


def test_budgeted_rrf_fusion_respects_quotas_and_dedup() -> None:
    r = HybridRetriever()

    vector = [
        _mk_result(doc_id="d1", chunk_index=0, score=0.99),
        _mk_result(doc_id="d2", chunk_index=0, score=0.97),
        _mk_result(doc_id="d3", chunk_index=0, score=0.80),
    ]
    bm25 = [
        _mk_result(doc_id="d2", chunk_index=0, score=12.0),
        _mk_result(doc_id="d4", chunk_index=0, score=10.0),
        _mk_result(doc_id="d5", chunk_index=0, score=9.0),
    ]
    lexical = [
        _mk_result(doc_id="d5", chunk_index=0, score=5.0),
        _mk_result(doc_id="d6", chunk_index=0, score=4.0),
    ]
    sparse = [
        _mk_result(doc_id="d7", chunk_index=0, score=3.0),
    ]

    out = r._merge_results(
        vector,
        bm25,
        lexical,
        sparse,
        alpha=0.5,
        fusion_strategy="budgeted_rrf",
        rrf_k=60,
        top_k=4,
    )

    keys = [r._result_key(x) for x in out[:4]]
    # Expected quotas (default): vector=2, bm25=1, lexical=1 (sparse gets 0 for top_k=4)
    # Dedup: d2:0 appears in vector+bm25; bm25 slot should skip it and take d4:0.
    assert set(keys) == {"d1:0", "d2:0", "d4:0", "d5:0"}
    assert len(keys) == 4
    scores = [float(x.get("score") or 0.0) for x in out[:4]]
    assert scores == sorted(scores, reverse=True)

    for item in out[:4]:
        assert item.get("fusion_strategy") == "budgeted_rrf"
        assert 0.0 <= float(item.get("score") or 0.0) <= 1.0
        # Rank-based calibrated scores should be present for observability.
        assert "vector_rank_score" in item
        assert "bm25_rank_score" in item
        assert "lexical_rank_score" in item
        assert "sparse_rank_score" in item


def test_budgeted_rrf_fusion_min_score_threshold_truncates_channel_queue() -> None:
    r = HybridRetriever().model_copy(
        update={
            # Force a quota that would try to take 2 lexical items.
            "fusion_budgets": {"vector": 2, "bm25": 1, "lexical": 2},
            # Only allow the first lexical item (rank_score==1.0).
            "fusion_min_scores": {"lexical": 1.0},
        }
    )

    vector = [
        _mk_result(doc_id="d1", chunk_index=0, score=0.99),
        _mk_result(doc_id="d2", chunk_index=0, score=0.97),
    ]
    bm25 = [
        _mk_result(doc_id="d3", chunk_index=0, score=10.0),
    ]
    lexical = [
        _mk_result(doc_id="d4", chunk_index=0, score=5.0),
        _mk_result(doc_id="d5", chunk_index=0, score=4.0),
    ]
    sparse = [
        _mk_result(doc_id="d6", chunk_index=0, score=3.0),
    ]

    out = r._merge_results(
        vector,
        bm25,
        lexical,
        sparse,
        alpha=0.5,
        fusion_strategy="budgeted_rrf",
        rrf_k=60,
        top_k=5,
    )

    keys = [r._result_key(x) for x in out[:5]]
    # Lexical has quota=2 but threshold keeps only the first lexical item.
    assert set(keys) == {"d1:0", "d2:0", "d3:0", "d4:0", "d6:0"}
    assert "d5:0" not in keys


def test_budgeted_rrf_weights_exact_hits_inside_existing_candidates() -> None:
    retriever = HybridRetriever()
    vector = [_mk_result(doc_id="d1", chunk_index=0, score=0.9, content="generic deployment notes")]
    exact_candidate = _mk_result(doc_id="d2", chunk_index=0, score=9.0, content="generic error notes")
    exact_candidate["metadata"]["_retrieval_text"] = "[keywords] error code abc-42"
    bm25 = [exact_candidate]

    out = retriever._merge_results(
        vector,
        bm25,
        query="ABC-42",
        fusion_strategy="budgeted_rrf",
        top_k=2,
    )

    assert [retriever._result_key(item) for item in out[:2]] == ["d2:0", "d1:0"]
    assert out[0]["exact_phrase_score"] == 1.0
    assert out[0]["exact_phrase_boost"] > 0.0


def test_family_collapse_deduplicates_candidates_without_hierarchy_expansion() -> None:
    retriever = HybridRetriever(hierarchy_family_collapse=True, enable_hierarchy_recall=False)
    results = [
        {
            **_mk_result(doc_id="d1", chunk_index=0, score=0.9),
            "metadata": {"document_id": "d1", "chunk_index": 0, "hierarchy_family_key": "family-a"},
        },
        {
            **_mk_result(doc_id="d1", chunk_index=1, score=0.8),
            "metadata": {"document_id": "d1", "chunk_index": 1, "hierarchy_family_key": "family-a"},
        },
        {
            **_mk_result(doc_id="d2", chunk_index=0, score=0.7),
            "metadata": {"document_id": "d2", "chunk_index": 0, "hierarchy_family_key": "family-b"},
        },
    ]
    stats: dict = {}

    out = retriever._collapse_results_by_family(results, stats=stats)

    assert [item["chunk_id"] for item in out] == ["d1:0", "d2:0"]
    assert stats["enabled"] is True
    assert stats["collapsed_results"] == 1


def test_candidate_metadata_priors_do_not_query_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY", True)
    monkeypatch.setattr(settings, "RETRIEVAL_GOVERNANCE_PREFER_LATEST", True)
    monkeypatch.setattr(settings, "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED", True)
    monkeypatch.setattr(
        "app.rag.retriever.SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("governance must not query the database")),
    )

    now = time.time()

    def candidate(
        doc_id: str,
        score: float,
        *,
        authority: int = 0,
        updated_ts: float = 0.0,
        publication_status: str = "published",
        supersedes: str = "",
    ) -> dict:
        result = _mk_result(doc_id=doc_id, chunk_index=0, score=score)
        result["metadata"].update(
            {
                "_governance_authority_level": authority,
                "_governance_updated_ts": updated_ts,
                "_governance_publication_status": publication_status,
                "_governance_supersedes_document_id": supersedes,
            }
        )
        return result

    results = [
        candidate("old", 0.99, authority=100, updated_ts=now),
        candidate("deprecated", 0.98, publication_status="deprecated"),
        candidate("new", 0.50, authority=100, updated_ts=now, supersedes="old"),
        candidate("authoritative", 0.50, authority=100, updated_ts=now),
        candidate("weak", 0.51, authority=0, updated_ts=now - 365 * 86400),
    ]
    stats: dict = {}

    out = HybridRetriever()._apply_governance_policy(results, stats=stats)
    doc_ids = [item["metadata"]["document_id"] for item in out]

    assert "old" not in doc_ids
    assert "deprecated" not in doc_ids
    assert doc_ids.index("authoritative") < doc_ids.index("weak")
    assert stats["filtered_superseded"] == 1
    assert stats["filtered_unpublished"] == 1
    assert stats["db_roundtrips"] == 0


def test_bm25_document_uses_index_text_but_keeps_display_body() -> None:
    retriever = HybridRetriever()
    prepared = retriever._prepare_retrieval_document(
        Document(
            page_content="Original Body",
            metadata={
                "_retrieval_display_content": "Original Body",
                "_retrieval_text": "[title] guide original body",
            },
        )
    )

    assert prepared.page_content == "[title] guide original body"
    assert retriever._result_content_from_doc(prepared) == "Original Body"


def test_default_fusion_reuses_budgeted_rrf() -> None:
    assert settings.RETRIEVAL_FUSION_STRATEGY == "budgeted_rrf"
    assert HybridRetriever().fusion_strategy == "budgeted_rrf"


def test_enterprise_profiles_gate_expensive_work_on_runtime_readiness() -> None:
    common = {
        "top_k": 5,
        "score_threshold": 0.2,
        "retrieval_mode": "hybrid",
        "enable_reranker": False,
        "reranker_provider": "none",
        "reranker_top_n": 20,
        "enable_weight_rerank": True,
    }

    fast = apply_retrieval_profile_overrides(profile="fast", **common)
    balanced = apply_retrieval_profile_overrides(profile="balanced", **common)
    quality = apply_retrieval_profile_overrides(profile="quality", **common)

    assert (fast["retrieval_mode"], fast["enable_reranker"], fast["sparse_retrieval_enabled"]) == (
        "vector",
        False,
        False,
    )
    assert fast["reranker_top_n"] >= 1
    assert (balanced["retrieval_mode"], balanced["enable_reranker"]) == ("hybrid", False)
    assert balanced.get("sparse_retrieval_enabled") is None
    assert quality["enable_hierarchy_recall"] is True
    assert quality["enable_reranker"] is False
    assert is_recall_first_profile("quality") is True

    ready = {**common, "enable_reranker": True, "reranker_provider": "cross_encoder"}
    balanced_ready = apply_retrieval_profile_overrides(profile="balanced", **ready)
    quality_ready = apply_retrieval_profile_overrides(profile="quality", **ready)

    assert balanced_ready["enable_reranker"] is True
    assert balanced_ready["reranker_provider"] == "cross_encoder"
    assert quality_ready["reranker_top_n"] > balanced_ready["reranker_top_n"]

    fast_config = ChatRAGConfig(retrieval_profile="fast")
    assert ChatRAGConfig.model_validate(fast_config.model_dump()).reranker_top_n >= 1
