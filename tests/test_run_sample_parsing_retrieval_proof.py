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

    assert report["cases_total"] == 3
    assert report["summary"]["hit_at_k_mean"] == 1.0
    assert report["summary"]["mrr_mean"] == 1.0
    assert (out_dir / "parsing_proof_batch.spec.json").exists()
    assert (out_dir / "batch.report.json").exists()


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
    assert payload["cases_total"] == 3
    assert payload["summary"]["hit_at_k_mean"] == 1.0
