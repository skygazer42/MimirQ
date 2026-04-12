from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "run_sample_parsing_retrieval_proof.py"
    spec = importlib.util.spec_from_file_location("run_sample_parsing_retrieval_proof", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_run_sample_parsing_retrieval_proof_writes_batch_outputs(tmp_path: Path) -> None:
    mod = _load_script()
    out_dir = tmp_path / "proof-run"

    report = mod.run_sample_parsing_retrieval_proof(  # type: ignore[attr-defined]
        manifest_path=_repo_root() / "tests" / "fixtures" / "parsing_golden_broader" / "manifest.json",
        case_queries_path=_repo_root() / "tests" / "fixtures" / "parsing_retrieval_proof" / "broader_case_queries.sample.json",
        out_dir=out_dir,
    )

    assert report["cases_total"] == 13
    assert report["query_count_total"] == 26
    assert len(report["cases"]) == 13
    assert report["summary"]["hit_at_k_mean"] == 1.0
    assert report["summary"]["mrr_mean"] == 1.0
    assert report["provenance"]["manifest_path"] == str(
        (_repo_root() / "tests" / "fixtures" / "parsing_golden_broader" / "manifest.json").resolve()
    )
    assert report["provenance"]["case_queries_path"] == str(
        (_repo_root() / "tests" / "fixtures" / "parsing_retrieval_proof" / "broader_case_queries.sample.json").resolve()
    )
    assert report["case_family_counts"]["specialty"] == 5
    assert report["case_family_counts"]["table"] == 4
    assert report["case_family_counts"]["layout"] == 3
    assert report["case_family_counts"]["document"] == 1
    report_payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    gate_payload = json.loads((out_dir / "gate.json").read_text(encoding="utf-8"))
    rollout_payload = json.loads((out_dir / "rollout.json").read_text(encoding="utf-8"))
    assert report_payload["rollout"]["current_stage"] == "informational"
    assert report_payload["rollout"]["next_stage"] == "warn"
    assert rollout_payload["schema"] == "mimirq.parsing_retrieval_proof_rollout.v1"
    assert gate_payload["provenance"]["rollout_path"] == str(
        (_repo_root() / "ci" / "parsing_retrieval_proof_rollout.v1.json").resolve()
    )
    assert (out_dir / "parsing_proof_batch.spec.json").exists()
    assert (out_dir / "batch.report.json").exists()
    assert (out_dir / "summary.json").exists()
    assert (out_dir / "report.json").exists()
    assert (out_dir / "rollout.json").exists()
    assert (out_dir / "gate.json").exists()
    assert (out_dir / "diff.json").exists()
    assert (out_dir / "diff.md").exists()
    assert (out_dir / "review.md").exists()


def test_run_sample_parsing_retrieval_proof_cli_writes_batch_report(tmp_path: Path) -> None:
    mod = _load_script()
    out_dir = tmp_path / "proof-run"

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--manifest-json",
            str(_repo_root() / "tests" / "fixtures" / "parsing_golden_broader" / "manifest.json"),
            "--case-queries-json",
            str(_repo_root() / "tests" / "fixtures" / "parsing_retrieval_proof" / "broader_case_queries.sample.json"),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    payload = json.loads((out_dir / "batch.report.json").read_text(encoding="utf-8"))
    assert payload["cases_total"] == 13
    assert payload["query_count_total"] == 26
    assert len(payload["cases"]) == 13
    assert payload["summary"]["hit_at_k_mean"] == 1.0
    assert payload["provenance"]["manifest_path"] == str(
        (_repo_root() / "tests" / "fixtures" / "parsing_golden_broader" / "manifest.json").resolve()
    )
    assert payload["provenance"]["case_queries_path"] == str(
        (_repo_root() / "tests" / "fixtures" / "parsing_retrieval_proof" / "broader_case_queries.sample.json").resolve()
    )
    assert payload["case_family_counts"]["specialty"] == 5
    assert payload["case_family_counts"]["document"] == 1
    report_payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    rollout_payload = json.loads((out_dir / "rollout.json").read_text(encoding="utf-8"))
    assert json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))["schema"] == "mimirq.parsing_retrieval_proof_summary.v1"
    assert json.loads((out_dir / "report.json").read_text(encoding="utf-8"))["schema"] == "mimirq.parsing_retrieval_proof_report.v1"
    assert json.loads((out_dir / "gate.json").read_text(encoding="utf-8"))["schema"] == "mimirq.parsing_retrieval_proof_gate_report.v1"
    assert json.loads((out_dir / "diff.json").read_text(encoding="utf-8"))["schema"] == "mimirq.parsing_retrieval_proof_diff.v1"
    assert report_payload["rollout"]["current_stage"] == "informational"
    assert rollout_payload["current_stage"] == "informational"
    assert "# Parsing Proof Review" in (out_dir / "review.md").read_text(encoding="utf-8")
