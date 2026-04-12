from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "build_parsing_retrieval_proof_review.py"
    spec = importlib.util.spec_from_file_location("build_parsing_retrieval_proof_review", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_parsing_proof_review_mentions_summary_checks_and_diff(tmp_path: Path) -> None:
    mod = _load_script()

    review = mod.build_review_markdown(  # type: ignore[attr-defined]
        summary={
            "cases_total": 5,
            "hit_at_k_mean": 1.0,
            "mrr_mean": 1.0,
            "failed_case_ids": [],
            "category_summaries": [
                {"name": "image", "cases_total": 2, "case_ids": ["chart_pdf_case", "qr_image_case"], "hit_at_k_mean": 1.0, "mrr_mean": 0.75, "failed_case_ids": ["qr_image_case"]}
            ],
            "slice_summaries": [
                {"name": "chart", "cases_total": 1, "case_ids": ["chart_pdf_case"], "hit_at_k_mean": 1.0, "mrr_mean": 1.0, "failed_case_ids": []},
                {"name": "qr", "cases_total": 1, "case_ids": ["qr_image_case"], "hit_at_k_mean": 1.0, "mrr_mean": 0.5, "failed_case_ids": ["qr_image_case"]},
            ],
            "cases": [{"id": "case-a", "hit_at_k": 1.0, "mrr": 1.0}],
        },
        report={
            "schema": "mimirq.parsing_retrieval_proof_report.v1",
            "summary_path": "artifacts/parsing_proof.summary.json",
            "checks": {
                "hit_at_k_mean": {"value": 1.0, "min": 1.0, "passed": True},
                "mrr_mean": {"value": 1.0, "min": 1.0, "passed": True},
            },
        },
        gate={"schema": "mimirq.parsing_retrieval_proof_gate_report.v1", "passed": True, "failures": []},
        diff={
            "schema": "mimirq.parsing_retrieval_proof_diff.v1",
            "metric_deltas": {"hit_at_k_mean_delta": 0.0, "mrr_mean_delta": 0.0},
            "failed_case_drift": {"added_ids": [], "removed_ids": []},
        },
    )

    assert "# Parsing Proof Review" in review
    assert "`cases_total`: `5`" in review
    assert "`hit_at_k_mean`: `1.0`" in review
    assert "`mrr_mean_delta`: `0.0`" in review
    assert "## Artifacts" in review
    assert "## Category Summary" in review
    assert "| image | 2 | 1.0 | 0.75 | qr_image_case |" in review
    assert "## Slice Summary" in review
    assert "| qr | 1 | 1.0 | 0.5 | qr_image_case |" in review
    assert "| Case | hit@k | mrr |" in review
    assert "| case-a | 1.0 | 1.0 |" in review


def test_build_parsing_proof_review_main_writes_markdown(tmp_path: Path) -> None:
    mod = _load_script()
    summary = tmp_path / "summary.json"
    report = tmp_path / "report.json"
    gate = tmp_path / "gate.json"
    diff = tmp_path / "diff.json"
    out = tmp_path / "review.md"

    summary.write_text(
        json.dumps(
            {
                "cases_total": 5,
                "hit_at_k_mean": 1.0,
                "mrr_mean": 1.0,
                "failed_case_ids": [],
                "category_summaries": [
                    {"name": "layout", "cases_total": 1, "case_ids": ["two_column_pdf_case"], "hit_at_k_mean": 1.0, "mrr_mean": 1.0, "failed_case_ids": []}
                ],
                "slice_summaries": [
                    {"name": "two_column", "cases_total": 1, "case_ids": ["two_column_pdf_case"], "hit_at_k_mean": 1.0, "mrr_mean": 1.0, "failed_case_ids": []}
                ],
                "cases": [{"id": "case-a", "hit_at_k": 1.0, "mrr": 1.0}],
            }
        ),
        encoding="utf-8",
    )
    report.write_text(
        json.dumps(
            {
                "schema": "mimirq.parsing_retrieval_proof_report.v1",
                "summary_path": "artifacts/parsing_proof.summary.json",
                "checks": {"hit_at_k_mean": {"value": 1.0, "min": 1.0, "passed": True}},
            }
        ),
        encoding="utf-8",
    )
    gate.write_text(
        json.dumps({"schema": "mimirq.parsing_retrieval_proof_gate_report.v1", "passed": True, "failures": []}),
        encoding="utf-8",
    )
    diff.write_text(
        json.dumps(
            {
                "schema": "mimirq.parsing_retrieval_proof_diff.v1",
                "metric_deltas": {"hit_at_k_mean_delta": 0.0, "mrr_mean_delta": 0.0},
                "failed_case_drift": {"added_ids": [], "removed_ids": []},
            }
        ),
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--summary",
            str(summary),
            "--report",
            str(report),
            "--gate",
            str(gate),
            "--diff",
            str(diff),
            "--out",
            str(out),
        ]
    )

    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "# Parsing Proof Review" in text
    assert "## Category Summary" in text
    assert "## Slice Summary" in text
