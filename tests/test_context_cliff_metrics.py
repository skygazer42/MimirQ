from __future__ import annotations

from pathlib import Path


def test_compute_context_cliff_metrics_flags_when_threshold_exceeded() -> None:
    from app.rag.core.context_cliff import compute_context_cliff_metrics

    out = compute_context_cliff_metrics(context_tokens=2600, threshold_tokens=2500)

    assert out["context_cliff_threshold_tokens"] == 2500
    assert out["context_cliff_triggered"] is True
    assert out["context_cliff_overflow_tokens"] == 100


def test_compute_context_cliff_metrics_is_noop_below_threshold() -> None:
    from app.rag.core.context_cliff import compute_context_cliff_metrics

    out = compute_context_cliff_metrics(context_tokens=1800, threshold_tokens=2500)

    assert out["context_cliff_triggered"] is False
    assert out["context_cliff_overflow_tokens"] == 0


def test_context_cliff_metrics_are_wired_into_generation_paths_source_contract() -> None:
    engine_src = Path("app/rag/engine.py").read_text(encoding="utf-8")
    langgraph_src = Path("app/rag/pipelines/langgraph.py").read_text(encoding="utf-8")

    assert "compute_context_cliff_metrics" in engine_src
    assert "RAG_CONTEXT_CLIFF_THRESHOLD_TOKENS" in engine_src
    assert "compute_context_cliff_metrics" in langgraph_src
    assert "RAG_CONTEXT_CLIFF_THRESHOLD_TOKENS" in langgraph_src
