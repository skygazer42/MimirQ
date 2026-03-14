from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "answer_quality_gate.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("answer_quality_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_extract_summary_supports_run_detail_shape() -> None:
    mod = _load_module()
    summary = mod.extract_summary(  # type: ignore[attr-defined]
        {
            "run": {
                "summary": {
                    "faithfulness_det": 0.8,
                }
            }
        }
    )
    assert summary["faithfulness_det"] == pytest.approx(0.8)


def test_evaluate_answer_quality_reports_threshold_failures() -> None:
    mod = _load_module()
    report = mod.evaluate_answer_quality(  # type: ignore[attr-defined]
        summary={"faithfulness_det": 0.2, "abstain_rate": 0.7},
        thresholds={
            "faithfulness_det": {"min": 0.3, "required": True},
            "abstain_rate": {"max": 0.6, "required": True},
        },
    )
    assert report["passed"] is False
    failures = list(report.get("failures") or [])
    assert any("faithfulness_det" in f for f in failures)
    assert any("abstain_rate" in f for f in failures)


def test_main_writes_gate_report(tmp_path: Path) -> None:
    mod = _load_module()
    inp = tmp_path / "summary.json"
    thresholds = tmp_path / "thresholds.json"
    out = tmp_path / "answer_quality.gate.json"
    inp.write_text(json.dumps({"summary": {"faithfulness_det": 0.8, "abstain_rate": 0.1}}), encoding="utf-8")
    thresholds.write_text(
        json.dumps(
            {
                "schema": "mimirq.answer_quality_thresholds.v1",
                "metrics": {
                    "faithfulness_det": {"min": 0.2, "required": True},
                    "abstain_rate": {"max": 0.6, "required": True},
                },
            }
        ),
        encoding="utf-8",
    )
    rc = mod.main(["--input", str(inp), "--thresholds", str(thresholds), "--out", str(out)])  # type: ignore[attr-defined]
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["passed"] is True
