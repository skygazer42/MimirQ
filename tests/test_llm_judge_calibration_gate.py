import json
from pathlib import Path

import pytest

from app.rag.evaluation.judge_calibration import build_calibration_report
from scripts.llm_judge_calibration_gate import main


def _rows(count: int, *, mismatches: int = 0) -> list[dict[str, str]]:
    labels = ("supported", "partial", "unsupported")
    rows: list[dict[str, str]] = []
    for index in range(count):
        human = labels[index % len(labels)]
        judge = labels[(index + 1) % len(labels)] if index < mismatches else human
        rows.append(
            {
                "case_id": f"case-{index:03d}",
                "human_label": human,
                "judge_label": judge,
                "reviewer_hash": "reviewer-deadbeef",
                "reviewed_at": "2026-08-16T10:00:00Z",
            }
        )
    return rows


def _payload(rows: list[dict[str, str]]) -> dict[str, object]:
    return {
        "schema": "mimirq.llm_judge_calibration.v1",
        "judge_version_hash": "judge-version-deadbeef",
        "dataset_version": "human-labels-2026-08",
        "label_policy_version": "support-rubric-v1",
        "items": rows,
    }


def test_calibration_report_requires_fifty_reviewed_items() -> None:
    with pytest.raises(ValueError, match="calibration_min_items:50"):
        build_calibration_report(
            _payload(_rows(49)),
        )


def test_calibration_report_computes_kappa_and_confusion() -> None:
    report = build_calibration_report(
        _payload(_rows(50, mismatches=5)),
    )

    assert report["items"] == 50
    assert report["reviewer_count"] == 1
    assert report["cohens_kappa"] == pytest.approx(0.85, abs=0.02)
    assert report["passed"] is True


def test_calibration_cli_fails_closed_for_low_agreement(tmp_path: Path) -> None:
    input_path = tmp_path / "labels.json"
    output_path = tmp_path / "report.json"
    input_path.write_text(
        json.dumps(_payload(_rows(50, mismatches=30))),
        encoding="utf-8",
    )

    rc = main(["--input", str(input_path), "--out", str(output_path)])

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert rc == 2
    assert report["passed"] is False
    assert report["cohens_kappa"] < 0.6
