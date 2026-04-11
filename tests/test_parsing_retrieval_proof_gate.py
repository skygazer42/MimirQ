from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_module():
    path = _repo_root() / "scripts" / "parsing_retrieval_proof_gate.py"
    spec = importlib.util.spec_from_file_location("parsing_retrieval_proof_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_extract_summary_supports_summary_shape() -> None:
    mod = _load_module()
    summary = mod.extract_summary(  # type: ignore[attr-defined]
        {
            "summary": {
                "hit_at_k_mean": 1.0,
                "mrr_mean": 0.75,
            }
        }
    )
    assert summary["hit_at_k_mean"] == 1.0
    assert summary["mrr_mean"] == 0.75


def test_evaluate_parsing_proof_reports_threshold_failures() -> None:
    mod = _load_module()
    report = mod.evaluate_parsing_proof(  # type: ignore[attr-defined]
        summary={"hit_at_k_mean": 1.0, "mrr_mean": 0.8},
        thresholds={
            "hit_at_k_mean": {"min": 1.0, "required": True},
            "mrr_mean": {"min": 0.9, "required": True},
        },
    )
    assert report["passed"] is False
    failures = list(report.get("failures") or [])
    assert any("mrr_mean" in f for f in failures)


def test_main_writes_gate_report(tmp_path: Path) -> None:
    mod = _load_module()
    inp = tmp_path / "summary.json"
    thresholds = tmp_path / "thresholds.json"
    out = tmp_path / "parsing_proof.gate.json"
    inp.write_text(json.dumps({"summary": {"hit_at_k_mean": 1.0, "mrr_mean": 1.0}}), encoding="utf-8")
    thresholds.write_text(
        json.dumps(
            {
                "schema": "mimirq.parsing_retrieval_proof_thresholds.v1",
                "metrics": {
                    "hit_at_k_mean": {"min": 1.0, "required": True},
                    "mrr_mean": {"min": 1.0, "required": True},
                },
            }
        ),
        encoding="utf-8",
    )
    rc = mod.main(["--input", str(inp), "--thresholds", str(thresholds), "--out", str(out)])  # type: ignore[attr-defined]
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["passed"] is True
