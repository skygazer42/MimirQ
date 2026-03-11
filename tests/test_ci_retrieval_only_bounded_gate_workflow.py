from __future__ import annotations

from pathlib import Path


def test_ci_has_retrieval_only_bounded_gate_job() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "retrieval-only-bounded-gate" in text
    assert "run_sample_retrieval_benchmark.py" in text
    assert "run_queryset_health_diagnostics.py" in text
    assert "ci/retrieval_thresholds.v2.json" in text
    assert "validate_queryset_health_policy.py" in text
    assert "ci/queryset_health_policy.v1.json" in text
    assert "artifacts/queryset_health.snapshot.json" in text
    assert "delta" in text.lower()
