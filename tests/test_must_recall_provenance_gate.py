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


def test_must_recall_provenance_gate_strict_integrity_checks_capsules(tmp_path) -> None:  # noqa: ANN001
    from app.rag.core.evidence_capsule_builder import build_evidence_capsule
    from scripts.must_recall_provenance_gate import run_gate

    capsule = build_evidence_capsule(
        query_for_retrieval="Revenue by region",
        citations=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
        metrics={"retrieval_mode": "hybrid"},
        retrieval_trace=None,
    )
    capsule["query_for_retrieval"] = "tampered"

    run_json = tmp_path / "run.json"
    run_json.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "metrics": {"must_recall_status": "passed", "must_recall_passed": True},
                        "evidence_capsule": capsule,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out = run_gate(
        run_json=run_json,
        must_recall_min=1.0,
        provenance_min=1.0,
        strict_integrity=True,
        require_signature=False,
    )
    assert bool(out.get("passed")) is False
    assert "provenance_integrity_rate_below_threshold" in list(out.get("failures") or [])
