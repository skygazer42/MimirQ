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
        summary={"cases_total": 5, "hit_at_k_mean": 1.0, "mrr_mean": 1.0, "failed_case_ids": []},
        report={"checks": [{"metric": "hit_at_k_mean", "value": 1.0, "min": 1.0, "passed": True}]},
        gate={"passed": True, "failures": []},
        diff={"metric_deltas": {"hit_at_k_mean_delta": 0.0, "mrr_mean_delta": 0.0}, "failed_case_drift": {"added_ids": [], "removed_ids": []}},
    )

    assert "# Parsing Proof Review" in review
    assert "`cases_total`: `5`" in review
    assert "`hit_at_k_mean`: `1.0`" in review
    assert "`mrr_mean_delta`: `0.0`" in review


def test_build_parsing_proof_review_main_writes_markdown(tmp_path: Path) -> None:
    mod = _load_script()
    summary = tmp_path / "summary.json"
    report = tmp_path / "report.json"
    gate = tmp_path / "gate.json"
    diff = tmp_path / "diff.json"
    out = tmp_path / "review.md"

    summary.write_text(json.dumps({"cases_total": 5, "hit_at_k_mean": 1.0, "mrr_mean": 1.0, "failed_case_ids": []}), encoding="utf-8")
    report.write_text(json.dumps({"checks": [{"metric": "hit_at_k_mean", "value": 1.0, "min": 1.0, "passed": True}]}), encoding="utf-8")
    gate.write_text(json.dumps({"passed": True, "failures": []}), encoding="utf-8")
    diff.write_text(json.dumps({"metric_deltas": {"hit_at_k_mean_delta": 0.0, "mrr_mean_delta": 0.0}, "failed_case_drift": {"added_ids": [], "removed_ids": []}}), encoding="utf-8")

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
    assert "# Parsing Proof Review" in out.read_text(encoding="utf-8")
