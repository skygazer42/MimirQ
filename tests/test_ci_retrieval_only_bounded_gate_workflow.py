from __future__ import annotations

from pathlib import Path


def test_ci_has_retrieval_only_bounded_gate_job() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    parsing_proof_surface = (
        "rollout.json",
        "summary.json",
        "report.json",
        "gate.json",
        "diff.json",
        "diff.md",
    )

    assert "retrieval-only-bounded-gate" in text
    assert "run_sample_retrieval_benchmark.py" in text
    assert "run_sample_parsing_retrieval_proof.py" in text
    assert "build_parsing_retrieval_proof_artifacts.py" in text
    assert "parsing_retrieval_proof_gate.py" in text
    assert "diff_parsing_retrieval_proof_summaries.py" in text
    assert "run_queryset_health_diagnostics.py" in text
    assert "diff_queryset_health_snapshots.py" in text
    assert "ci/retrieval_thresholds.v2.json" in text
    assert "validate_queryset_health_policy.py" in text
    assert "ci/parser_strict_profile.v1.json" in text
    assert "generate_adaptive_router_policy.py" in text
    assert "generate_channel_budget_policy.py" in text
    assert "export_intent_router_training.py" in text
    assert "generate_intent_router_model.py" in text
    assert "answer_quality_gate.py" in text
    assert "ci/answer_quality_thresholds.v1.json" in text
    assert "ci/queryset_health_snapshot_baseline.v1.json" in text
    assert "ci/queryset_health_snapshot_hybrid_baseline.v1.json" in text
    assert "ci/queryset_health_snapshot_sparse_baseline.v1.json" in text
    assert "data/sample/retrieval_fixture_hybrid_v1.json" in text
    assert "data/sample/retrieval_fixture_colbert_v1.json" in text
    assert "data/sample/retrieval_fixture_sparse_v1.json" in text
    assert "ci/queryset_health_policy.v1.json" in text
    assert "ci/parsing_retrieval_proof_thresholds.v1.json" in text
    assert "ci/parsing_retrieval_proof_summary_baseline.v1.json" in text
    assert "--batch-report artifacts/parsing_proof_broader_sample/batch.report.json" in text
    assert "--summary-out artifacts/parsing_proof_broader_sample/summary.json" in text
    assert "--report-out artifacts/parsing_proof_broader_sample/report.json" in text
    assert "--input artifacts/parsing_proof_broader_sample/summary.json" in text
    assert "--a ci/parsing_retrieval_proof_summary_baseline.v1.json" in text
    assert "--b artifacts/parsing_proof_broader_sample/summary.json" in text
    assert "artifacts/queryset_health.snapshot.json" in text
    assert "artifacts/queryset_health.snapshot.hybrid.json" in text
    assert "artifacts/queryset_health.snapshot.sparse.json" in text
    assert "artifacts/queryset_health.diff.json" in text
    assert "artifacts/queryset_health.diff.md" in text
    assert "artifacts/queryset_health.diff.hybrid.json" in text
    assert "artifacts/queryset_health.diff.hybrid.md" in text
    assert "artifacts/queryset_health.diff.sparse.json" in text
    assert "artifacts/queryset_health.diff.sparse.md" in text
    assert "artifacts/sample_retrieval_bench.colbert.json" in text
    assert "artifacts/sample_retrieval_bench.sparse.json" in text
    assert "artifacts/adaptive_router_policy.v1.json" in text
    assert "artifacts/channel_budget_policy.v1.json" in text
    assert "artifacts/intent_router_training.v1.json" in text
    assert "artifacts/intent_router_model.v1.json" in text
    assert "artifacts/answer_quality.summary.json" in text
    assert "artifacts/answer_quality.gate.json" in text
    assert "artifacts/multihop_diagnostics.summary.json" in text
    assert "ci_retrieval_only_bounded_gate_colbert" in text
    assert "ci_retrieval_only_bounded_gate_sparse" in text
    assert "ci_retrieval_only_bounded_gate_hybrid" in text
    assert "grounded_strict" in text
    assert "artifacts/retrieval_profile.grounded_strict.contract.json" in text
    assert "artifacts/claim_verifier.contract.json" in text
    assert "verify_claim" in text
    assert "delta" in text.lower()

    for artifact_name in parsing_proof_surface:
        assert f"artifacts/parsing_proof_broader_sample/{artifact_name}" in text
        assert f"bounded_gate_artifacts/artifacts/parsing_proof_broader_sample/{artifact_name}" in text

    assert "bounded_gate_artifacts/artifacts/parsing_proof_broader_sample/review.md" in text
    assert "bounded_gate_artifacts/artifacts/parsing_proof_broader_sample/rollout.json" in text

    sample_index = text.index("run_sample_parsing_retrieval_proof.py")
    build_index = text.index("build_parsing_retrieval_proof_artifacts.py")
    gate_index = text.index("parsing_retrieval_proof_gate.py")
    diff_index = text.index("diff_parsing_retrieval_proof_summaries.py")
    assert sample_index < build_index < gate_index < diff_index
