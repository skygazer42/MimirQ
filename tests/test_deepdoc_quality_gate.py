from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "deepdoc_quality_gate.py"


def _load_module():
    path = _script_path()
    if not path.exists():
        pytest.skip("deepdoc quality gate script not implemented yet")
    spec = importlib.util.spec_from_file_location("deepdoc_quality_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_deepdoc_gate_extracts_cases_from_prior_report_shape(tmp_path: Path) -> None:
    mod = _load_module()
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "dataset_id": "ds-1",
                "cases": [
                    {
                        "id": "bert_name",
                        "doc": "bert",
                        "q": "What does BERT stand for?",
                        "groups": [["bidirectional"], ["encoder", "representations"]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cases = mod.load_cases(report)  # type: ignore[attr-defined]

    assert len(cases) == 1
    assert cases[0]["id"] == "bert_name"
    assert cases[0]["question"] == "What does BERT stand for?"
    assert cases[0]["fact_groups"][0] == ["bidirectional"]


def test_deepdoc_gate_summary_enforces_accuracy_and_latency_thresholds() -> None:
    mod = _load_module()
    rows = [
        {"kind": "retrieve", "ok": True, "elapsed_ms": 100.0, "source_top1": True, "source_hit": True, "fact_hit": True},
        {"kind": "retrieve", "ok": True, "elapsed_ms": 300.0, "source_top1": False, "source_hit": True, "fact_hit": False},
        {"kind": "chat", "ok": True, "elapsed_ms": 1200.0, "source_top1": True, "source_hit": True, "fact_hit": True},
        {"kind": "chat", "ok": False, "elapsed_ms": 2000.0, "source_top1": False, "source_hit": False, "fact_hit": False},
    ]

    summary = mod.summarize_rows(rows)  # type: ignore[attr-defined]
    gate = mod.evaluate_gate(
        summary,
        thresholds={
            "retrieve": {"min_ok_rate": 1.0, "min_source_hit_rate": 1.0, "min_fact_hit_rate": 0.8, "max_p95_ms": 250.0},
            "chat": {"min_ok_rate": 1.0, "min_source_hit_rate": 0.9, "min_fact_hit_rate": 0.9, "max_p95_ms": 1500.0},
        },
    )

    assert summary["retrieve"]["ok_rate"] == pytest.approx(1.0)
    assert summary["retrieve"]["source_hit_rate"] == pytest.approx(1.0)
    assert gate["passed"] is False
    failures = "\n".join(gate["failures"])
    assert "retrieve.fact_hit_rate" in failures
    assert "retrieve.p95_ms" in failures
    assert "chat.ok_rate" in failures


def test_deepdoc_gate_extracts_runtime_metrics_from_response_body() -> None:
    mod = _load_module()

    metrics = mod.extract_runtime_metrics(  # type: ignore[attr-defined]
        {
            "metrics": {
                "retrieval_elapsed_sec": 1.25,
                "retrieval_query_count": 3,
                "retrieval_query_parallelism": 2,
                "kg_chunks_injected": 2,
                "kg_chunk_boost_promoted": 1,
                "kg_query_expansion_used": True,
            }
        },
        elapsed_ms=1500.0,
    )

    assert metrics["server_retrieval_ms"] == pytest.approx(1250.0)
    assert metrics["api_overhead_ms"] == pytest.approx(250.0)
    assert metrics["retrieval_query_count"] == 3
    assert metrics["retrieval_query_parallelism"] == 2
    assert metrics["kg_chunks_injected"] == 2
    assert metrics["kg_chunk_boost_promoted"] == 1
    assert metrics["kg_query_expansion_used"] is True


def test_deepdoc_gate_summary_includes_runtime_and_kg_usage() -> None:
    mod = _load_module()
    rows = [
        {
            "kind": "retrieve",
            "variant": "kg_boost",
            "ok": True,
            "elapsed_ms": 1000.0,
            "server_retrieval_ms": 700.0,
            "api_overhead_ms": 300.0,
            "source_hit": True,
            "fact_hit": True,
            "fact_group_count": 1,
            "kg_chunks_injected": 1,
            "kg_chunk_boost_promoted": 1,
            "kg_query_expansion_used": False,
        },
        {
            "kind": "retrieve",
            "variant": "kg_boost",
            "ok": True,
            "elapsed_ms": 1200.0,
            "server_retrieval_ms": 900.0,
            "api_overhead_ms": 300.0,
            "source_hit": True,
            "fact_hit": False,
            "fact_group_count": 1,
            "kg_chunks_injected": 0,
            "kg_chunk_boost_promoted": 0,
            "kg_query_expansion_used": True,
        },
    ]

    summary = mod.summarize_rows(rows)  # type: ignore[attr-defined]
    runtime = summary["retrieve:kg_boost"]["runtime"]
    kg = summary["retrieve:kg_boost"]["kg"]

    assert runtime["server_retrieval_p95_ms"] == pytest.approx(900.0)
    assert runtime["api_overhead_p95_ms"] == pytest.approx(300.0)
    assert kg["chunks_injected_total"] == 1
    assert kg["boost_promoted_total"] == 1
    assert kg["query_expansion_used_rate"] == pytest.approx(0.5)


def test_deepdoc_gate_diagnostics_payload_is_compact() -> None:
    mod = _load_module()

    diagnostics = mod.summarize_dataset_diagnostics(  # type: ignore[attr-defined]
        {
            "total_documents": 3,
            "total_chunks": 42,
            "total_size": 12345,
            "total_characters": 67890,
            "by_status": {"completed": 3},
        },
        {
            "events": 12,
            "entities": 8,
            "links": 30,
            "entity_types": [{"type": "concept", "count": 8}],
        },
        {
            "summary": {
                "documents": 3,
                "events": 12,
                "entities": 8,
                "event_entity_links": 30,
                "orphan_entities": 1,
            }
        },
    )

    assert diagnostics["ingestion"]["total_documents"] == 3
    assert diagnostics["ingestion"]["total_chunks"] == 42
    assert diagnostics["kg_stats"]["events"] == 12
    assert diagnostics["kg_quality"]["links"] == 30
    assert diagnostics["kg_quality"]["orphan_entities"] == 1


def test_deepdoc_gate_ignores_thresholds_for_modes_not_run() -> None:
    mod = _load_module()

    gate = mod.evaluate_gate(  # type: ignore[attr-defined]
        {"kg": {"ok_rate": 1.0, "source_hit_rate": 1.0, "fact_hit_rate": 1.0, "latency": {"p95_ms": 100.0}}},
        thresholds={
            "kg": {"min_ok_rate": 1.0, "max_p95_ms": 500.0},
            "chat": {"min_ok_rate": 1.0},
        },
    )

    assert gate["passed"] is True
    assert gate["failures"] == []


def test_quality_suite_accepts_deepdoc_gate_phase() -> None:
    suite_path = _repo_root() / "scripts" / "rag_pipeline_quality_suite.py"
    spec = importlib.util.spec_from_file_location("rag_pipeline_quality_suite", str(suite_path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    args = mod.parse_args(
        [
            "--deepdoc-dataset-id",
            "dac642d4-bf63-4072-b819-cc34c053e176",
            "--deepdoc-cases",
            "artifacts/final-local-readiness/20260526-deepdoc-expanded-qa-concurrency/report.json",
            "--deepdoc-modes",
            "retrieve,chat,kg",
        ]
    )

    phases = mod.build_phases(args)
    phase = {item.name: item for item in phases}["deepdoc_quality_gate"]

    assert phase.required is True
    assert "scripts/deepdoc_quality_gate.py" in phase.command
    assert "--dataset-id" in phase.command
    assert "retrieve,chat,kg" in phase.command
