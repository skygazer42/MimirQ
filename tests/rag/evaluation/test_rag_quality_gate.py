from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.core.config import Settings


def _load_summary(path: str) -> dict[str, float]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("summary payload must be an object")
    return {
        "faithfulness": float(payload.get("faithfulness", 0.0) or 0.0),
        "answer_relevancy": float(payload.get("answer_relevancy", 0.0) or 0.0),
        "context_precision": float(payload.get("context_precision", 0.0) or 0.0),
    }


def _assert_quality_gate(settings: Settings, summary: dict[str, float]) -> None:
    assert summary["faithfulness"] >= float(settings.RAG_EVAL_GATE_FAITHFULNESS_MIN), (
        f"Faithfulness {summary['faithfulness']:.3f} < {settings.RAG_EVAL_GATE_FAITHFULNESS_MIN:.3f}"
    )
    assert summary["answer_relevancy"] >= float(settings.RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN), (
        f"Answer relevancy {summary['answer_relevancy']:.3f} < {settings.RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN:.3f}"
    )
    assert summary["context_precision"] >= float(settings.RAG_EVAL_GATE_CONTEXT_PRECISION_MIN), (
        f"Context precision {summary['context_precision']:.3f} < {settings.RAG_EVAL_GATE_CONTEXT_PRECISION_MIN:.3f}"
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _builder_script_path() -> Path:
    return _repo_root() / "scripts" / "build_rag_quality_gate_artifacts.py"


def _load_builder_module():
    path = _builder_script_path()
    spec = importlib.util.spec_from_file_location("build_rag_quality_gate_artifacts", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_rag_quality_gate_defaults_off() -> None:
    assert Settings.model_fields["RAG_EVAL_GATE_ENABLED"].default is False


def test_rag_quality_gate_default_thresholds_are_expected() -> None:
    assert float(Settings.model_fields["RAG_EVAL_GATE_FAITHFULNESS_MIN"].default) == pytest.approx(0.80)
    assert float(Settings.model_fields["RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN"].default) == pytest.approx(0.75)
    assert float(Settings.model_fields["RAG_EVAL_GATE_CONTEXT_PRECISION_MIN"].default) == pytest.approx(0.70)


def test_rag_quality_gate_fails_when_metrics_below_thresholds(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "faithfulness": 0.79,
                "answer_relevancy": 0.74,
                "context_precision": 0.69,
            }
        ),
        encoding="utf-8",
    )
    summary = _load_summary(str(summary_path))
    with pytest.raises(AssertionError):
        _assert_quality_gate(Settings(), summary)


def test_build_answer_quality_summary_uses_benchmark_metrics() -> None:
    mod = _load_builder_module()
    payload = mod.build_answer_quality_summary(  # type: ignore[attr-defined]
        {
            "summary": {
                "mrr": 0.81,
                "ndcg_at_k": 0.73,
                "hit_at_k": 0.92,
            }
        }
    )
    assert payload == {
        "schema": "mimirq.answer_quality_summary.v1",
        "faithfulness": pytest.approx(0.81),
        "answer_relevancy": pytest.approx(0.73),
        "context_precision": pytest.approx(0.92),
    }


def test_build_rag_quality_gate_report_uses_threshold_checks() -> None:
    mod = _load_builder_module()
    report = mod.build_rag_quality_gate_report(  # type: ignore[attr-defined]
        {
            "faithfulness": 0.81,
            "answer_relevancy": 0.72,
            "context_precision": 0.91,
        },
        summary_path="artifacts/answer_quality.summary.json",
        thresholds={
            "faithfulness": 0.80,
            "answer_relevancy": 0.75,
            "context_precision": 0.70,
        },
    )
    assert set(report) == {"schema", "summary_path", "thresholds", "checks", "passed"}
    assert report["schema"] == "mimirq.rag_quality_gate_report.v1"
    assert report["summary_path"] == "artifacts/answer_quality.summary.json"
    assert set(report["thresholds"]) == {"faithfulness", "answer_relevancy", "context_precision"}
    assert report["thresholds"]["answer_relevancy"] == pytest.approx(0.75)
    assert set(report["checks"]) == {"faithfulness", "answer_relevancy", "context_precision"}
    for metric in ("faithfulness", "answer_relevancy", "context_precision"):
        assert set(report["checks"][metric]) == {"value", "min", "passed"}
    assert report["checks"]["faithfulness"]["passed"] is True
    assert report["checks"]["answer_relevancy"]["passed"] is False
    assert report["passed"] is False


def test_rag_quality_gate_builder_main_preserves_relative_summary_path(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    mod = _load_builder_module()
    bench_path = tmp_path / "sample_retrieval_bench.json"
    bench_path.write_text(
        json.dumps({"summary": {"mrr": 0.91, "ndcg_at_k": 0.42, "hit_at_k": 0.73}}),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--benchmark",
            str(bench_path),
            "--summary-out",
            "artifacts/answer_quality.summary.json",
            "--report-out",
            "artifacts/rag_quality_gate.report.json",
        ]
    )

    assert rc == 0
    report = json.loads((tmp_path / "artifacts" / "rag_quality_gate.report.json").read_text(encoding="utf-8"))
    assert report["summary_path"] == "artifacts/answer_quality.summary.json"


@pytest.mark.skipif(not Settings().RAG_EVAL_GATE_ENABLED, reason="RAG quality gate disabled")
def test_rag_quality_gate_uses_sample_summary() -> None:
    cfg = Settings()
    summary = _load_summary(cfg.RAG_EVAL_GATE_SUMMARY_PATH)
    _assert_quality_gate(cfg, summary)


def test_rag_quality_gate_workflow_exists() -> None:
    text = Path(".github/workflows/rag-quality-gate.yml").read_text(encoding="utf-8")
    assert "RAG Quality Gate" in text
    assert "tests/rag/evaluation/test_rag_quality_gate.py" in text
    assert "RAG_EVAL_GATE_ENABLED" in text
    assert "RAG_EVAL_GATE_SUMMARY_PATH" in text
    assert "scripts/run_sample_retrieval_benchmark.py" in text
    assert text.count("scripts/run_sample_retrieval_benchmark.py") >= 2
    assert "scripts/build_rag_quality_gate_artifacts.py" in text
    assert text.count("scripts/build_rag_quality_gate_artifacts.py") >= 2
    assert "scripts/run_sample_parsing_retrieval_proof.py" in text
    assert "scripts/build_parsing_retrieval_proof_artifacts.py" in text
    assert "scripts/parsing_retrieval_proof_gate.py" in text
    assert "data/sample/retrieval_fixture_v1.json" in text
    assert text.count("data/sample/retrieval_fixture_v1.json") >= 2
    assert "artifacts/answer_quality.summary.json" in text
    assert "artifacts/rag_quality_gate.report.json" in text
    assert "artifacts/parsing_proof_broader_sample/summary.json" in text
    assert "artifacts/parsing_proof_broader_sample/report.json" in text
    assert "artifacts/parsing_proof_broader_sample/gate.json" in text
    assert "artifacts/parsing_proof_broader_sample/diff.json" in text
    assert "artifacts/parsing_proof_broader_sample/diff.md" in text
    assert "artifacts/parsing_proof_broader_sample/review.md" in text
    assert "actions/upload-artifact@v4" in text
