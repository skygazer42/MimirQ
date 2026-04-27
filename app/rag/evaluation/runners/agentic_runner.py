from __future__ import annotations

from typing import Any

from app.rag.agents.rag_agent import get_agentic_runner
from app.rag.evaluation.runners.base import build_runner_result


async def run_agentic_route(sample: dict[str, Any]) -> dict[str, Any]:
    runner = get_agentic_runner()
    answer_parts: list[str] = []
    citations: list[dict[str, Any]] = []
    done_payload: dict[str, Any] = {}
    async for event in runner.stream(question=str(sample.get("query") or ""), history=[]):
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        data = event.get("data") or {}
        if event_type == "citations" and isinstance(data, list):
            citations = list(data)
        elif event_type == "token" and isinstance(data, dict):
            token = str(data.get("content") or "")
            if token:
                answer_parts.append(token)
        elif event_type == "done" and isinstance(data, dict):
            done_payload = dict(data)

    metrics = dict(done_payload.get("metrics") or {})
    return build_runner_result(
        sample_id=str(sample.get("sample_id") or ""),
        route_id="agentic",
        query_type=str(sample.get("query_type") or ""),
        source_type=str(sample.get("source_type") or ""),
        expected_route=sample.get("expected_route"),
        actual_route=str(done_payload.get("route") or "agentic"),
        answer={"text": "".join(answer_parts)},
        citations=citations,
        latency_ms=metrics.get("elapsed_sec"),
        token_cost=metrics.get("agentic_tools_used"),
        route_config={"mode": "agentic"},
        evaluators={},
        agentic_iterations=metrics.get("agentic_rounds"),
        agentic_latency_ms=metrics.get("generation_elapsed_sec"),
        agentic_token_cost=done_payload.get("total_tokens"),
        agentic_status="completed",
    )
