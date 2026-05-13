from __future__ import annotations


def test_hybrid_alpha_defaults_share_single_settings_source() -> None:
    from app.core.config import Settings
    from app.rag.retriever import HybridRetriever, HybridSearchOptions

    default_alpha = float(Settings.model_fields["RETRIEVAL_DEFAULT_ALPHA"].default)

    assert default_alpha == 0.6
    assert HybridSearchOptions().alpha == default_alpha
    assert HybridRetriever().alpha == default_alpha


def test_hybrid_runner_sweeps_rrf_alpha_and_top_k_from_channel_rankings() -> None:
    from app.rag.evaluation.runners.hybrid_runner import build_hybrid_sweep_configs, run_hybrid_sweep

    sample = {
        "sample_id": "hybrid-alpha-case",
        "gold_chunk_ids": ["gold-1"],
        "hybrid_channels": {
            "vector": ["vec-only", "vec-second", "gold-1"],
            "bm25": ["gold-1", "keyword-only"],
        },
    }
    configs = build_hybrid_sweep_configs(alpha_values=[0.2, 0.95], rrf_k_values=[10], top_k_values=[1])

    report = run_hybrid_sweep(sample, configs=configs)

    assert [row["label"] for row in report["rows"]] == [
        "fusion=rrf__rrf_k=10__alpha=0.2__top_k=1",
        "fusion=rrf__rrf_k=10__alpha=0.95__top_k=1",
    ]
    assert report["best"]["route_config"] == {
        "fusion": "rrf",
        "rrf_k": 10,
        "alpha": 0.2,
        "top_k": 1,
    }
    assert report["best"]["retrieved_chunk_ids"] == ["gold-1"]
    assert report["best"]["evaluators"]["retrieval"]["recall_at_k"] == 1.0
    assert report["rows"][1]["evaluators"]["retrieval"]["recall_at_k"] == 0.0
