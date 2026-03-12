from __future__ import annotations

from pathlib import Path


def test_ci_has_retrieval_only_bounded_gate_job() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "retrieval-only-bounded-gate" in text
    assert "run_sample_retrieval_benchmark.py" in text
    assert "run_queryset_health_diagnostics.py" in text
    assert "diff_queryset_health_snapshots.py" in text
    assert "ci/retrieval_thresholds.v2.json" in text
    assert "validate_queryset_health_policy.py" in text
    assert "ci/queryset_health_snapshot_baseline.v1.json" in text
    assert "ci/queryset_health_snapshot_hybrid_baseline.v1.json" in text
    assert "data/sample/retrieval_fixture_hybrid_v1.json" in text
    assert "ci/queryset_health_policy.v1.json" in text
    assert "artifacts/queryset_health.snapshot.json" in text
    assert "artifacts/queryset_health.snapshot.hybrid.json" in text
    assert "artifacts/queryset_health.diff.json" in text
    assert "artifacts/queryset_health.diff.md" in text
    assert "artifacts/queryset_health.diff.hybrid.json" in text
    assert "artifacts/queryset_health.diff.hybrid.md" in text
    assert "ci_retrieval_only_bounded_gate_hybrid" in text
    assert "grounded_strict" in text
    assert "artifacts/retrieval_profile.grounded_strict.contract.json" in text
    assert "delta" in text.lower()
