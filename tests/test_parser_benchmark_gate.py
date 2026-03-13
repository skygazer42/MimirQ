from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "parser_benchmark.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("parser_benchmark", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_evaluate_strict_regressions_detects_metric_drop() -> None:
    mod = _load_module()
    out = mod.evaluate_strict_regressions(  # type: ignore[attr-defined]
        current_summary={
            "auto": {
                "ok_rate": 0.80,
                "parse_score_mean": 0.70,
            }
        },
        baseline_summary={
            "auto": {
                "ok_rate": 0.90,
                "parse_score_mean": 0.76,
            }
        },
        max_drop_by_metric={
            "ok_rate": 0.02,
            "parse_score_mean": 0.03,
        },
    )
    assert out["passed"] is False
    failures = list(out.get("failures") or [])
    assert any("auto.ok_rate" in str(msg) for msg in failures)
    assert any("parse_score_mean" in str(msg) for msg in failures)


def test_evaluate_strict_regressions_passes_within_threshold() -> None:
    mod = _load_module()
    out = mod.evaluate_strict_regressions(  # type: ignore[attr-defined]
        current_summary={
            "auto": {
                "ok_rate": 0.89,
                "parse_score_mean": 0.75,
            }
        },
        baseline_summary={
            "auto": {
                "ok_rate": 0.90,
                "parse_score_mean": 0.76,
            }
        },
        max_drop_by_metric={
            "ok_rate": 0.02,
            "parse_score_mean": 0.03,
        },
    )
    assert out["passed"] is True
    assert list(out.get("failures") or []) == []
