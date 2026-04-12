from __future__ import annotations

import json
from pathlib import Path


def test_ci_release_gate_consumes_bounded_queryset_artifacts() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "actions/download-artifact@v4" in text
    assert "retrieval-only-bounded-gate" in text
    assert "--queryset-health-snapshot" in text
    assert "--queryset-health-snapshot-hybrid" in text
    assert "--queryset-health-diff" in text
    assert "--queryset-health-diff-hybrid" in text
    assert "--probe-retrieval-mode hybrid" in text
    assert "bounded_gate_artifacts/artifacts/queryset_health.snapshot.json" in text
    assert "bounded_gate_artifacts/artifacts/queryset_health.snapshot.hybrid.json" in text
    assert "bounded_gate_artifacts/artifacts/queryset_health.diff.json" in text
    assert "bounded_gate_artifacts/artifacts/queryset_health.diff.hybrid.json" in text
    assert "bounded_gate_artifacts/artifacts/parsing_proof_broader_sample/summary.json" in text
    assert "bounded_gate_artifacts/artifacts/parsing_proof_broader_sample/report.json" in text
    assert "bounded_gate_artifacts/artifacts/parsing_proof_broader_sample/diff.json" in text
    assert "continue-on-error: true" not in text


def test_release_gate_budgets_include_queryset_drift_thresholds() -> None:
    payload = json.loads(Path("ci/release_gate_budgets.v1.json").read_text(encoding="utf-8"))

    assert payload.get("schema") == "mimirq.release_gate_budgets.v1"

    default_diff = payload.get("queryset_health_diff")
    hybrid_diff = payload.get("queryset_health_diff_hybrid")
    default_snapshot = payload.get("queryset_health")
    hybrid_snapshot = payload.get("queryset_health_hybrid")

    assert isinstance(default_snapshot, dict)
    assert isinstance(hybrid_snapshot, dict)
    assert isinstance(default_diff, dict)
    assert isinstance(hybrid_diff, dict)

    for cfg in (default_diff, hybrid_diff):
        thresholds = cfg.get("thresholds") if isinstance(cfg, dict) else {}
        assert thresholds == {
            "hard_case_added_count": {"max": 0},
            "degradation_flag_added_count": {"max": 0},
            "parse_risk_tail_added_count": {"max": 0},
        }
