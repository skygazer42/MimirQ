from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


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
                "mean_seal_recall": 0.20,
            }
        },
        baseline_summary={
            "auto": {
                "ok_rate": 0.90,
                "parse_score_mean": 0.76,
                "mean_seal_recall": 0.80,
            }
        },
        max_drop_by_metric={
            "ok_rate": 0.02,
            "parse_score_mean": 0.03,
            "mean_seal_recall": 0.10,
        },
    )
    assert out["passed"] is False
    failures = list(out.get("failures") or [])
    assert any("auto.ok_rate" in str(msg) for msg in failures)
    assert any("parse_score_mean" in str(msg) for msg in failures)
    assert any("mean_seal_recall" in str(msg) for msg in failures)


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


def test_resolve_strict_thresholds_prefers_profile_values() -> None:
    mod = _load_module()
    args = SimpleNamespace(
        strict_max_ok_rate_drop=0.02,
        strict_max_parse_score_drop=0.03,
        strict_max_golden_similarity_drop=0.03,
        strict_max_golden_coverage_drop=0.05,
        strict_max_seal_recall_drop=0.06,
        strict_max_equation_recall_drop=0.07,
        strict_max_table_recall_drop=0.08,
        strict_max_image_recall_drop=0.09,
    )
    thresholds = mod.resolve_strict_thresholds(  # type: ignore[attr-defined]
        args=args,
        strict_profile={
            "schema": "mimirq.parser_benchmark_strict_profile.v1",
            "thresholds": {
                "ok_rate": 0.9,
                "parse_score_mean": 0.8,
                "golden_similarity_mean": 0.7,
                "golden_coverage_ratio_mean": 0.6,
                "mean_seal_recall": 0.5,
                "mean_equation_recall": 0.4,
            },
        },
    )
    assert thresholds["ok_rate"] == pytest.approx(0.9)
    assert thresholds["parse_score_mean"] == pytest.approx(0.8)
    assert thresholds["golden_similarity_mean"] == pytest.approx(0.7)
    assert thresholds["golden_coverage_ratio_mean"] == pytest.approx(0.6)
    assert thresholds["mean_seal_recall"] == pytest.approx(0.5)
    assert thresholds["mean_equation_recall"] == pytest.approx(0.4)
    assert thresholds["mean_table_recall"] == pytest.approx(0.08)
    assert thresholds["mean_image_recall"] == pytest.approx(0.09)


def test_load_strict_profile_requires_known_schema(tmp_path: Path) -> None:
    mod = _load_module()
    p = tmp_path / "strict_profile.json"
    p.write_text(json.dumps({"schema": "invalid", "thresholds": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        mod.load_strict_profile(p)  # type: ignore[attr-defined]


def test_build_regression_severity_summary_emits_levels() -> None:
    mod = _load_module()
    out = mod.build_regression_severity_summary(  # type: ignore[attr-defined]
        current_summary={"auto": {"ok_rate": 0.6}},
        baseline_summary={"auto": {"ok_rate": 0.9}},
        max_drop_by_metric={"ok_rate": 0.1},
        severity_bands={"critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.5},
    )
    assert out["schema"] == "mimirq.parser_benchmark_regression_severity.v1"
    levels = out.get("levels") or {}
    assert levels.get("critical") == 1
    items = list(out.get("items") or [])
    assert items
    assert items[0]["metric"] == "ok_rate"
