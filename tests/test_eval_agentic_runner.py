from __future__ import annotations

import asyncio

from app.rag.evaluation.runners.agentic_runner import run_agentic_route
from app.rag.evaluation.runners.registry import get_runner


def test_runner_registry_exposes_agentic_runner_after_batch_b() -> None:
    runner = get_runner("agentic")
    assert runner is not None


def test_run_agentic_route_adapts_stream_events_into_unified_result(monkeypatch):  # noqa: ANN001
    class _DummyRunner:
        async def stream(self, **_kwargs):  # noqa: ANN003
            yield {"type": "route", "data": {"route": "agentic"}}
            yield {"type": "agentic_step", "data": {"step": "planning"}}
            yield {"type": "citations", "data": [{"chunk_id": "chunk-1"}]}
            yield {"type": "token", "data": {"content": "agentic answer"}}
            yield {"type": "done", "data": {"metrics": {"agentic_rounds": 2}, "route": "agentic"}}

    import app.rag.evaluation.runners.agentic_runner as module

    monkeypatch.setattr(module, "get_agentic_runner", lambda **_kwargs: _DummyRunner(), raising=True)

    result = asyncio.run(
        run_agentic_route(
            {
                "sample_id": "stage1-002",
                "query": "根据报警和 schema 解释 485 掉线原因",
                "query_type": "multi_hop",
                "source_type": "manual_seed",
                "expected_route": "agentic",
            }
        )
    )

    assert result["route_id"] == "agentic"
    assert result["actual_route"] == "agentic"
    assert result["answer"]["text"] == "agentic answer"
    assert result["agentic_iterations"] == 2
    assert result["agentic_status"] == "completed"
