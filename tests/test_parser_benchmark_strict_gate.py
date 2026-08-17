import json
import sys
from pathlib import Path

from langchain_core.documents import Document

import app.parsing.factory as factory_module
import app.parsing.processors.cross_page_merge as cross_page_merge_module
import app.parsing.quality.document_quality as document_quality_module
import app.parsing.quality.text_quality as text_quality_module
import scripts.parser_benchmark as benchmark_module
from scripts.parser_benchmark import (
    BenchmarkCase,
    build_regression_severity_summary,
    evaluate_baseline_compatibility,
    evaluate_strict_regressions,
)


class _DummyTextQuality:
    def to_dict(self) -> dict[str, float]:
        return {"score": 0.9}


def test_strict_gate_rejects_an_empty_baseline_summary() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": 1.0}},
        baseline_summary={},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["baseline summary is missing or empty"]


def test_strict_gate_rejects_a_missing_baseline_backend() -> None:
    result = evaluate_strict_regressions(
        current_summary={},
        baseline_summary={"basic": {"ok_rate": 1.0}},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic backend is missing from the current summary"]


def test_strict_gate_rejects_a_missing_current_metric() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": 1.0}},
        baseline_summary={"basic": {"ok_rate": 1.0, "parse_score_mean": 0.8}},
        max_drop_by_metric={"ok_rate": 0.02, "parse_score_mean": 0.03},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic.parse_score_mean is missing from the current summary"]


def test_strict_gate_rejects_a_missing_baseline_metric() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": 1.0}},
        baseline_summary={"basic": {}},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic.ok_rate is missing from the baseline summary"]


def test_strict_gate_rejects_malformed_metric_values() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": "not-a-number"}},
        baseline_summary={"basic": {"ok_rate": 1.0}},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic.ok_rate has a non-numeric current value"]


def test_strict_gate_rejects_non_finite_metric_values() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": "NaN"}},
        baseline_summary={"basic": {"ok_rate": 1.0}},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic.ok_rate has a non-numeric current value"]


def test_strict_gate_rejects_non_finite_thresholds() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": 1.0}},
        baseline_summary={"basic": {"ok_rate": 1.0}},
        max_drop_by_metric={"ok_rate": float("nan")},
    )

    assert result["passed"] is False
    assert result["failures"] == ["ok_rate has a non-numeric maximum drop"]


def test_strict_gate_rejects_a_malformed_baseline_backend() -> None:
    result = evaluate_strict_regressions(
        current_summary={"basic": {"ok_rate": 1.0}},
        baseline_summary={"basic": "invalid"},
        max_drop_by_metric={"ok_rate": 0.02},
    )

    assert result["passed"] is False
    assert result["failures"] == ["basic backend has an invalid baseline summary"]


def test_strict_gate_rejects_missing_compatibility_hashes() -> None:
    result = evaluate_baseline_compatibility(
        current_report={"fixture_hash": "fixture", "profile_hash": "profile"},
        baseline_report={},
    )

    assert result == {
        "compatible": False,
        "mismatches": [
            "fixture_hash missing from baseline report",
            "profile_hash missing from baseline report",
        ],
    }


def test_regression_severity_summary_sorts_by_ratio_and_caps_items() -> None:
    summary = build_regression_severity_summary(
        current_summary={
            "beta": {"ok_rate": 0.5, "parse_score_mean": 0.7},
            "alpha": {"ok_rate": 0.89},
        },
        baseline_summary={
            "beta": {"ok_rate": 0.9, "parse_score_mean": 0.9},
            "alpha": {"ok_rate": 1.0},
        },
        max_drop_by_metric={"ok_rate": 0.1, "parse_score_mean": 0.1},
        severity_bands={"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5},
    )

    assert summary["schema"] == "mimirq.parser_benchmark_regression_severity.v1"
    assert summary["levels"] == {"critical": 1, "high": 1, "medium": 1, "low": 0}
    assert [(item["backend"], item["metric"], item["level"], item["ratio"]) for item in summary["items"]] == [
        ("beta", "ok_rate", "critical", 4.0),
        ("beta", "parse_score_mean", "high", 2.0),
        ("alpha", "ok_rate", "medium", 1.1),
    ]


def test_main_strict_without_baseline_writes_failure_report(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    input_path = tmp_path / "case.txt"
    input_path.write_text("example input", encoding="utf-8")
    out_path = tmp_path / "report.json"
    case = BenchmarkCase(case_id="case-1", path=input_path)

    monkeypatch.setattr(benchmark_module, "_load_cases", lambda *_args, **_kwargs: [case])
    monkeypatch.setattr(
        factory_module.parser_factory,
        "parse_with_provenance",
        lambda path, parser_backend, pdf_quality=None: (
            [Document(page_content=f"parsed:{path.name}:{parser_backend}", metadata={})],
            parser_backend,
            {"source": "stub"},
        ),
    )
    monkeypatch.setattr(cross_page_merge_module, "merge_cross_page_documents", lambda docs: docs)
    monkeypatch.setattr(text_quality_module, "score_parsed_text_quality", lambda markdown: _DummyTextQuality())
    monkeypatch.setattr(
        document_quality_module,
        "score_document_parse_quality",
        lambda **kwargs: {"score": 0.75},
    )
    monkeypatch.setattr(benchmark_module, "_reading_order_score", lambda markdown: 0.5)
    monkeypatch.setattr(benchmark_module, "_count_specialty_elements", lambda documents: {})
    monkeypatch.setattr(benchmark_module, "_count_image_visual_kinds", lambda documents: {})
    monkeypatch.setattr(benchmark_module, "_collect_image_code_values", lambda documents: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parser_benchmark.py",
            "--input-dir",
            str(tmp_path),
            "--out",
            str(out_path),
            "--backends",
            "basic",
            "--strict",
        ],
    )

    rc = benchmark_module.main()

    captured = capsys.readouterr()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert rc == 2
    assert "[parser-benchmark] wrote" in captured.out
    assert "[parser-benchmark] strict gate failed: baseline_required" in captured.out
    assert payload["schema"] == "mimirq.parser_benchmark.v1"
    assert payload["backends"] == ["basic"]
    assert payload["strict_gate"] == {
        "enabled": True,
        "passed": False,
        "reason": "baseline_required",
        "failures": ["strict mode requires --baseline to exist"],
    }
    assert payload["cases"][0]["attempts"][0]["resolved_backend"] == "basic"


def test_main_preserves_backend_order_and_summary_aggregation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "case.txt"
    input_path.write_text("example input", encoding="utf-8")
    out_path = tmp_path / "report.json"
    case = BenchmarkCase(case_id="case-1", path=input_path)
    seen_backends: list[str] = []
    perf_values = iter([10.0, 10.012, 20.0, 20.034])
    last_perf_value = 20.034

    def _perf_counter() -> float:
        nonlocal last_perf_value
        try:
            last_perf_value = next(perf_values)
        except StopIteration:
            pass
        return last_perf_value

    def _parse(path: Path, parser_backend: str, pdf_quality=None):
        seen_backends.append(parser_backend)
        return (
            [Document(page_content=f"parsed:{path.name}:{parser_backend}", metadata={})],
            f"resolved-{parser_backend}",
            {"backend": parser_backend},
        )

    monkeypatch.setattr(benchmark_module, "_load_cases", lambda *_args, **_kwargs: [case])
    monkeypatch.setattr(factory_module.parser_factory, "parse_with_provenance", _parse)
    monkeypatch.setattr(cross_page_merge_module, "merge_cross_page_documents", lambda docs: docs)
    monkeypatch.setattr(text_quality_module, "score_parsed_text_quality", lambda markdown: _DummyTextQuality())
    monkeypatch.setattr(
        document_quality_module,
        "score_document_parse_quality",
        lambda **kwargs: {"score": 0.75},
    )
    monkeypatch.setattr(benchmark_module, "_reading_order_score", lambda markdown: 0.5)
    monkeypatch.setattr(benchmark_module, "_count_specialty_elements", lambda documents: {})
    monkeypatch.setattr(benchmark_module, "_count_image_visual_kinds", lambda documents: {})
    monkeypatch.setattr(benchmark_module, "_collect_image_code_values", lambda documents: {})
    monkeypatch.setattr(benchmark_module.time, "perf_counter", _perf_counter)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parser_benchmark.py",
            "--input-dir",
            str(tmp_path),
            "--out",
            str(out_path),
            "--backends",
            "BASIC,AUTO",
        ],
    )

    rc = benchmark_module.main()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert seen_backends == ["basic", "auto"]
    assert payload["backends"] == ["basic", "auto"]
    assert [attempt["backend"] for attempt in payload["cases"][0]["attempts"]] == ["basic", "auto"]
    assert payload["cases"][0]["attempts"][0]["resolved_backend"] == "resolved-basic"
    assert payload["cases"][0]["attempts"][1]["resolved_backend"] == "resolved-auto"
    assert payload["summary"]["basic"] == {
        "attempts": 1,
        "ok": 1,
        "ok_rate": 1.0,
        "elapsed_ms_p50": payload["cases"][0]["attempts"][0]["elapsed_ms"],
        "elapsed_ms_p90": payload["cases"][0]["attempts"][0]["elapsed_ms"],
        "parse_score_mean": 0.75,
        "golden_similarity_mean": None,
        "golden_coverage_ratio_mean": None,
        "golden_image_ref_recall_mean": None,
        "mean_table_continuity_recall": None,
        "mean_table_grits_topology": None,
        "mean_table_grits_content": None,
        "mean_table_grits_f1": None,
        "mean_reading_order_score": 0.5,
        "mean_seal_recall": None,
        "mean_equation_recall": None,
        "mean_table_recall": None,
        "mean_image_recall": None,
        "mean_chart_image_recall": None,
        "mean_qr_image_recall": None,
        "mean_barcode_image_recall": None,
        "mean_diagram_image_recall": None,
        "mean_qr_code_value_recall": None,
        "mean_barcode_code_value_recall": None,
    }
    assert payload["summary"]["auto"]["elapsed_ms_p50"] == payload["cases"][0]["attempts"][1]["elapsed_ms"]
    assert payload["summary"]["auto"]["elapsed_ms_p90"] == payload["cases"][0]["attempts"][1]["elapsed_ms"]
    assert payload["summary"]["auto"]["parse_score_mean"] == 0.75
