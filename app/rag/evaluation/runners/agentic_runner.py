from contextlib import aclosing
from typing import Any

from app.rag.agents.rag_agent import AgenticStreamRequest, get_agentic_runner
from app.rag.evaluation.runners.base import build_runner_result


def _seconds_to_ms(value: float | None) -> float | None:
    return value * 1000.0 if value is not None else None


async def run_agentic_route(sample: dict[str, Any]) -> dict[str, Any]:
    runner = get_agentic_runner()
    answer_parts: list[str] = []
    citations: list[dict[str, Any]] = []
    done_payload: dict[str, Any] | None = None
    request = AgenticStreamRequest(question=sample["query"], history=[])
    async with aclosing(runner.stream(request=request)) as events:
        async for event in events:
            event_type = event["type"]
            data = event.get("data")
            if event_type == "error":
                raise RuntimeError("Agentic evaluation runner emitted an error event")
            if event_type == "citations" and isinstance(data, list):
                citations = list(data)
            elif event_type == "token" and isinstance(data, dict):
                token = data["content"]
                if token:
                    answer_parts.append(token)
            elif event_type == "done" and isinstance(data, dict):
                done_payload = dict(data)

    if done_payload is None:
        raise RuntimeError("Agentic evaluation runner ended without a completion event")

    metrics = dict(done_payload.get("metrics") or {})
    return build_runner_result(
        sample_id=sample["sample_id"],
        route_id="agentic",
        query_type=sample["query_type"],
        source_type=sample["source_type"],
        expected_route=sample.get("expected_route"),
        actual_route=str(done_payload.get("route") or "agentic"),
        answer={"text": "".join(answer_parts)},
        citations=citations,
        latency_ms=_seconds_to_ms(metrics.get("elapsed_sec")),
        token_cost=None,
        route_config={"mode": "agentic", "model_used": done_payload.get("model_used")},
        evaluators={},
        agentic_iterations=metrics.get("agentic_rounds"),
        agentic_latency_ms=_seconds_to_ms(metrics.get("generation_elapsed_sec")),
        agentic_token_cost=done_payload.get("total_tokens"),
        agentic_status="completed",
        extensions={"agentic_tools_used": metrics.get("agentic_tools_used")},
    )
