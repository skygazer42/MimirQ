from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "build_parsing_retrieval_proof_artifacts.py"
    spec = importlib.util.spec_from_file_location("build_parsing_retrieval_proof_artifacts", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_parsing_proof_summary_uses_batch_metrics() -> None:
    mod = _load_script()
    payload = mod.build_parsing_proof_summary(  # type: ignore[attr-defined]
        {
            "cases_total": 2,
            "summary": {"hit_at_k_mean": 1.0, "mrr_mean": 0.75},
            "cases": [
                {"id": "case-a", "summary": {"hit_at_k": 1.0, "mrr": 1.0}},
                {"id": "case-b", "summary": {"hit_at_k": 1.0, "mrr": 0.5}},
            ],
        }
    )
    assert payload["schema"] == "mimirq.parsing_retrieval_proof_summary.v1"
    assert payload["cases_total"] == 2
    assert payload["hit_at_k_mean"] == 1.0
    assert payload["mrr_mean"] == 0.75
    assert payload["failed_case_ids"] == ["case-b"]


def test_build_parsing_proof_report_uses_threshold_checks() -> None:
    mod = _load_script()
    report = mod.build_parsing_proof_report(  # type: ignore[attr-defined]
        {
            "hit_at_k_mean": 1.0,
            "mrr_mean": 0.75,
            "failed_case_ids": ["case-b"],
        },
        summary_path="artifacts/parsing_proof.summary.json",
        thresholds={"hit_at_k_mean": 1.0, "mrr_mean": 0.8},
    )
    assert report["schema"] == "mimirq.parsing_retrieval_proof_report.v1"
    assert report["summary_path"] == "artifacts/parsing_proof.summary.json"
    assert report["checks"]["hit_at_k_mean"]["passed"] is True
    assert report["checks"]["mrr_mean"]["passed"] is False
    assert report["failed_case_ids"] == ["case-b"]
    assert report["passed"] is False


def test_parsing_proof_artifacts_builder_main_writes_relative_summary_path(tmp_path: Path, monkeypatch) -> None:
    mod = _load_script()
    batch_path = tmp_path / "batch.report.json"
    batch_path.write_text(
        json.dumps(
            {
                "cases_total": 1,
                "summary": {"hit_at_k_mean": 1.0, "mrr_mean": 1.0},
                "cases": [{"id": "case-a", "summary": {"hit_at_k": 1.0, "mrr": 1.0}}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--batch-report",
            str(batch_path),
            "--summary-out",
            "artifacts/parsing_proof.summary.json",
            "--report-out",
            "artifacts/parsing_proof.report.json",
        ]
    )

    assert rc == 0
    report = json.loads((tmp_path / "artifacts" / "parsing_proof.report.json").read_text(encoding="utf-8"))
    assert report["summary_path"] == "artifacts/parsing_proof.summary.json"
