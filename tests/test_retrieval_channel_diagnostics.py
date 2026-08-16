
from app.rag.retrieval.hybrid.channel_diagnostics import update_hybrid_channel_diagnostics


def test_update_hybrid_channel_diagnostics_populates_counts_and_payloads() -> None:
    channel_metrics = {
        "timing": {},
        "counts": {},
        "colbert_ann": {"readiness": {"effective_provider": "ann"}},
    }
    keyword_strategy = {"primary": "lexical_db"}

    update_hybrid_channel_diagnostics(
        channel_metrics=channel_metrics,
        vector_results=[{"score": 0.9}],
        bm25_results=[{"score": 0.8}],
        lexical_results=[
            {"score": 0.7, "metadata": {"lexical_method": "fts"}},
            {"score": 0.6, "metadata": {"lexical_method": "trgm"}},
            {"score": 0.5, "metadata": {}},
        ],
        sparse_results=[{"score": 0.4}],
        colpali_results=[],
        vector_elapsed_ms=12.345,
        colbert_elapsed_ms=2.2,
        bm25_elapsed_ms=3.3,
        lexical_elapsed_ms=4.4,
        colbert_candidates=5,
        colbert_used=True,
        colbert_retrieval_enabled=True,
        colbert_provider="fallback",
        retrieval_mode="hybrid",
        fusion_strategy="budgeted_rrf",
        rrf_k=60,
        fusion_weights={"vector": 0.6, "bm25": 0.4},
        vector_backend="milvus",
        want_vector=True,
        want_bm25=True,
        want_lexical=True,
        want_sparse=True,
        want_colpali=False,
        vector_filter_applied=True,
        bm25_filter_applied=False,
        bm25_index_enabled=True,
        last_bm25_status={"ready": True},
        lexical_run_reason="hybrid_parallel",
        lexical_hybrid_fallback_only=False,
        lexical_db_enabled=True,
        lexical_db_fts_config="simple",
        lexical_db_trgm_enabled=True,
        lexical_pg_trgm_available=True,
        metadata_exact_pre_fusion_stats={"enabled": True, "annotated": 2, "promoted": 1},
        colpali_reason="disabled",
        sparse_provider_status={
            "requested_provider": "splade",
            "requested_provider_normalized": "splade",
            "effective_provider": "deterministic",
            "provider_supported": False,
            "model_required": True,
            "model_configured": False,
            "status": "fallback",
            "reason": "model_missing",
            "outcome": "degraded",
        },
        sparse_provider="splade",
        keyword_strategy=keyword_strategy,
    )

    assert channel_metrics["timing"] == {
        "vector_ms": 12.35,
        "colbert_ms": 2.2,
        "bm25_ms": 3.3,
        "lexical_ms": 4.4,
    }
    assert channel_metrics["counts"] == {
        "vector_candidates": 1,
        "colbert_candidates": 5,
        "colpali_candidates": 0,
        "bm25_candidates": 1,
        "lexical_candidates": 3,
        "sparse_candidates": 1,
    }
    assert channel_metrics["colbert_ann"]["provider"] == "ann"
    assert channel_metrics["lexical_db"]["methods"] == {"fts": 1, "trgm": 1, "unknown": 1}
    assert channel_metrics["sparse"]["provider"] == "deterministic"
    assert channel_metrics["metadata_exact_pre_fusion"] == {"enabled": True, "annotated": 2, "promoted": 1}
    assert channel_metrics["keyword_strategy"] == {
        "primary": "lexical_db",
        "bm25_used": True,
        "lexical_db_used": True,
        "sparse_used": True,
    }


def test_update_hybrid_channel_diagnostics_omits_empty_fusion_weights() -> None:
    channel_metrics = {"timing": {}, "counts": {}}

    update_hybrid_channel_diagnostics(
        channel_metrics=channel_metrics,
        vector_results=[],
        bm25_results=[],
        lexical_results=[],
        sparse_results=[],
        colpali_results=[{"score": 0.5}],
        vector_elapsed_ms=0.0,
        colbert_elapsed_ms=0.0,
        bm25_elapsed_ms=0.0,
        lexical_elapsed_ms=0.0,
        colbert_candidates=0,
        colbert_used=False,
        colbert_retrieval_enabled=False,
        colbert_provider="",
        retrieval_mode="keyword",
        fusion_strategy="weighted",
        rrf_k=0,
        fusion_weights=None,
        vector_backend="",
        want_vector=False,
        want_bm25=False,
        want_lexical=False,
        want_sparse=False,
        want_colpali=True,
        vector_filter_applied=False,
        bm25_filter_applied=False,
        bm25_index_enabled=False,
        last_bm25_status={},
        lexical_run_reason="not_run",
        lexical_hybrid_fallback_only=True,
        lexical_db_enabled=False,
        lexical_db_fts_config="simple",
        lexical_db_trgm_enabled=False,
        lexical_pg_trgm_available=None,
        metadata_exact_pre_fusion_stats={},
        colpali_reason="image_query",
        sparse_provider_status={},
        sparse_provider="deterministic",
        keyword_strategy=None,
    )

    assert channel_metrics["fusion_weights"] is None
    assert channel_metrics["colpali"] == {
        "enabled": True,
        "used": True,
        "candidates": 1,
        "reason": "image_query",
    }
