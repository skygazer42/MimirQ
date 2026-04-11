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
        strict_max_golden_image_ref_recall_drop=0.04,
        strict_max_seal_recall_drop=0.06,
        strict_max_equation_recall_drop=0.07,
        strict_max_table_recall_drop=0.08,
        strict_max_image_recall_drop=0.09,
        strict_max_chart_image_recall_drop=0.11,
        strict_max_qr_image_recall_drop=0.12,
        strict_max_barcode_image_recall_drop=0.125,
        strict_max_diagram_image_recall_drop=0.13,
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
                "golden_image_ref_recall_mean": 0.55,
                "mean_seal_recall": 0.5,
                "mean_equation_recall": 0.4,
                "mean_chart_image_recall": 0.3,
                "mean_qr_image_recall": 0.2,
                "mean_barcode_image_recall": 0.15,
                "mean_diagram_image_recall": 0.1,
            },
        },
    )
    assert thresholds["ok_rate"] == pytest.approx(0.9)
    assert thresholds["parse_score_mean"] == pytest.approx(0.8)
    assert thresholds["golden_similarity_mean"] == pytest.approx(0.7)
    assert thresholds["golden_coverage_ratio_mean"] == pytest.approx(0.6)
    assert thresholds["golden_image_ref_recall_mean"] == pytest.approx(0.55)
    assert thresholds["mean_seal_recall"] == pytest.approx(0.5)
    assert thresholds["mean_equation_recall"] == pytest.approx(0.4)
    assert thresholds["mean_table_recall"] == pytest.approx(0.08)
    assert thresholds["mean_image_recall"] == pytest.approx(0.09)
    assert thresholds["mean_chart_image_recall"] == pytest.approx(0.3)
    assert thresholds["mean_qr_image_recall"] == pytest.approx(0.2)
    assert thresholds["mean_barcode_image_recall"] == pytest.approx(0.15)
    assert thresholds["mean_diagram_image_recall"] == pytest.approx(0.1)


def test_load_strict_profile_requires_known_schema(tmp_path: Path) -> None:
    mod = _load_module()
    p = tmp_path / "strict_profile.json"
    p.write_text(json.dumps({"schema": "invalid", "thresholds": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        mod.load_strict_profile(p)  # type: ignore[attr-defined]


def test_evaluate_baseline_compatibility_detects_fixture_and_profile_mismatch() -> None:
    mod = _load_module()
    out = mod.evaluate_baseline_compatibility(  # type: ignore[attr-defined]
        current_report={"fixture_hash": "fixture-new", "profile_hash": "profile-new"},
        baseline_report={"fixture_hash": "fixture-old", "profile_hash": "profile-old"},
    )
    assert out["compatible"] is False
    mismatches = list(out.get("mismatches") or [])
    assert any("fixture_hash" in item for item in mismatches)
    assert any("profile_hash" in item for item in mismatches)


def test_build_fixture_hash_tracks_binary_fixture_bytes(tmp_path: Path) -> None:
    mod = _load_module()
    sample = tmp_path / "sample.png"
    sample.write_bytes(b"\x89PNG\r\n\x1a\nbinary-a")

    first = mod._build_fixture_hash(  # type: ignore[attr-defined]
        cases=[mod.BenchmarkCase(case_id="img", path=sample)],  # type: ignore[attr-defined]
        manifest_path=None,
    )

    sample.write_bytes(b"\x89PNG\r\n\x1a\nbinary-b")
    second = mod._build_fixture_hash(  # type: ignore[attr-defined]
        cases=[mod.BenchmarkCase(case_id="img", path=sample)],  # type: ignore[attr-defined]
        manifest_path=None,
    )

    assert isinstance(first, str) and len(first) == 24
    assert isinstance(second, str) and len(second) == 24
    assert first != second


def test_build_fixture_hash_tracks_markdown_referenced_assets(tmp_path: Path) -> None:
    mod = _load_module()
    case_root = tmp_path / "chart_case"
    (case_root / "input").mkdir(parents=True, exist_ok=True)
    (case_root / "golden").mkdir(parents=True, exist_ok=True)
    (case_root / "input" / "sample.md").write_text("![chart](chart.png)\n", encoding="utf-8")
    (case_root / "golden" / "sample.md").write_text("![chart](chart.png)\n", encoding="utf-8")
    (case_root / "input" / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\nchart-a")
    (case_root / "golden" / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\nchart-a")

    first = mod._build_fixture_hash(  # type: ignore[attr-defined]
        cases=[
            mod.BenchmarkCase(  # type: ignore[attr-defined]
                case_id="chart-case",
                path=case_root / "input" / "sample.md",
                golden_markdown_path=case_root / "golden" / "sample.md",
            )
        ],
        manifest_path=None,
    )

    (case_root / "input" / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\nchart-b")
    second = mod._build_fixture_hash(  # type: ignore[attr-defined]
        cases=[
            mod.BenchmarkCase(  # type: ignore[attr-defined]
                case_id="chart-case",
                path=case_root / "input" / "sample.md",
                golden_markdown_path=case_root / "golden" / "sample.md",
            )
        ],
        manifest_path=None,
    )

    assert first != second


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
