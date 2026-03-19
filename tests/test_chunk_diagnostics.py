from __future__ import annotations


def test_compute_chunk_diagnostics_basic_metrics() -> None:
    from app.rag.evaluation.chunk_diagnostics import compute_chunk_diagnostics

    answer = "Alice lives in Paris.\nBob lives in Berlin.\nCharlie lives in Rome."
    contexts = [
        "Alice lives in Paris.",
        "Bob lives in Berlin.",
    ]
    diag = compute_chunk_diagnostics(
        answer=answer,
        retrieved_contexts=contexts,
        context_relevance=[True, False],
        reference_evidence_text="Alice lives in Paris.\nBob lives in Berlin.\nCharlie lives in Rome.",
    )

    assert diag["chunk_utilization"] == 1.0
    assert diag["chunk_attribution"] == 0.6667
    assert diag["noise_sensitivity"] == 0.5
    assert diag["self_knowledge_ratio"] == 0.3333

    counts = diag["counts"]
    assert counts["claims_total"] == 3
    assert counts["claims_supported"] == 2
    assert counts["claims_noisy"] == 1
    assert counts["claims_correct_total"] == 3
    assert counts["claims_correct_uncited"] == 1
    assert counts["chunks_total"] == 2
    assert counts["chunks_used"] == 2

