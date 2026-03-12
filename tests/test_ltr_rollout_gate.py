from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _load_gate_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "ltr_rollout_gate.py"
    spec = importlib.util.spec_from_file_location("ltr_rollout_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _comparison_payload(*, mrr_delta: float, cases_used: int = 2) -> dict[str, Any]:
    from app.services.ltr_rollout_workflow import build_rollout_comparison

    candidate_mrr = round(0.5 + float(mrr_delta), 4)
    return build_rollout_comparison(
        generated_at="2026-03-12T00:00:00Z",
        candidate_eval={
            "schema": "mimirq.ltr_offline_eval.v1",
            "cases_total": 3,
            "cases_used": int(cases_used),
            "k": 20,
            "top_k": 50,
            "baseline": {"hit": 0.6, "mrr": 0.4, "recall": 0.7, "ndcg": 0.45},
            "ltr": {"hit": 0.7, "mrr": candidate_mrr, "recall": 0.8, "ndcg": 0.55},
            "lineage": {"model_sha256": "c" * 64},
        },
        baseline_eval={
            "schema": "mimirq.ltr_offline_eval.v1",
            "cases_total": 3,
            "cases_used": int(cases_used),
            "k": 20,
            "top_k": 50,
            "ltr": {"hit": 0.6, "mrr": 0.5, "recall": 0.7, "ndcg": 0.5},
            "lineage": {"model_sha256": "b" * 64},
        },
        active_model_id="active-1",
        candidate_model_id="candidate-1",
    )


def test_evaluate_ltr_rollout_gate_passes_when_deltas_meet_default_thresholds() -> None:
    from app.services.ltr_rollout_workflow import evaluate_ltr_rollout_gate

    comparison = _comparison_payload(mrr_delta=0.1, cases_used=3)
    gate = evaluate_ltr_rollout_gate(comparison=comparison)

    assert gate["schema"] == "mimirq.ltr_rollout_gate_result.v1"
    assert gate["passed"] is True
    assert gate["summary"]["failed"] == 0
    assert gate["reasons"] == []


def test_evaluate_ltr_rollout_gate_fails_when_metric_regresses() -> None:
    from app.services.ltr_rollout_workflow import evaluate_ltr_rollout_gate

    comparison = _comparison_payload(mrr_delta=-0.2, cases_used=3)
    gate = evaluate_ltr_rollout_gate(comparison=comparison, thresholds={"metrics": {"delta.mrr": {"min": 0.0}}})

    assert gate["passed"] is False
    assert gate["summary"]["failed"] == 1
    assert any("delta.mrr" in str(reason) for reason in gate["reasons"])


def test_ltr_rollout_gate_cli_supports_workflow_payload_and_threshold_overrides(tmp_path: Path) -> None:
    mod = _load_gate_script()
    comparison = _comparison_payload(mrr_delta=0.05, cases_used=2)
    workflow_payload = {
        "schema": "mimirq.ltr_rollout_workflow.v1",
        "comparison": comparison,
    }
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(json.dumps(workflow_payload), encoding="utf-8")

    rc_ok = mod.main(["--input", str(workflow_path), "--min-delta-mrr", "0.01"])  # type: ignore[attr-defined]
    rc_fail = mod.main(["--input", str(workflow_path), "--min-delta-mrr", "0.1"])  # type: ignore[attr-defined]

    assert rc_ok == 0
    assert rc_fail == 3
