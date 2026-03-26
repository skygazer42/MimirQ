from __future__ import annotations

import json
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
    assert "artifacts/answer_quality.summary.json" in text
    assert "artifacts/rag_quality_gate.report.json" in text
    assert "actions/upload-artifact@v4" in text
