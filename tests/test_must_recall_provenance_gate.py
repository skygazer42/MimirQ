from __future__ import annotations

import json


def test_must_recall_provenance_gate_passes_with_valid_summary(tmp_path) -> None:  # noqa: ANN001
    from scripts.must_recall_provenance_gate import run_gate

    run_json = tmp_path / "run.json"
    run_json.write_text(
        json.dumps(
            {
                "summary": {
                    "total_cases": 2,
                    "must_recall_pass_rate": 1.0,
                    "must_recall_passed_cases": 2,
                    "provenance_integrity_rate": 1.0,
                    "provenance_passed_cases": 2,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out = run_gate(run_json=run_json, must_recall_min=0.9, provenance_min=0.9)
    assert bool(out.get("passed")) is True
    assert list(out.get("failures") or []) == []


def test_must_recall_provenance_gate_fails_when_rates_below_threshold(tmp_path) -> None:  # noqa: ANN001
    from scripts.must_recall_provenance_gate import run_gate

    run_json = tmp_path / "run.json"
    run_json.write_text(
        json.dumps(
            {
                "summary": {
                    "total_cases": 2,
                    "must_recall_pass_rate": 0.5,
                    "provenance_integrity_rate": 0.0,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out = run_gate(run_json=run_json, must_recall_min=1.0, provenance_min=1.0)
    assert bool(out.get("passed")) is False
    failures = list(out.get("failures") or [])
    assert "must_recall_pass_rate_below_threshold" in failures
    assert "provenance_integrity_rate_below_threshold" in failures
