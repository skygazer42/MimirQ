from __future__ import annotations

from app.rag.kg.search.agentic_beam_search import run_agentic_beam_search


def test_run_agentic_beam_search_expands_seed_entities_with_beam_limit() -> None:
    out = run_agentic_beam_search(
        query="Trace why the watchdog alarm caused the 485 bus failure.",
        topic_entities=["watchdog", "485 bus"],
        adjacency={
            "watchdog": ["alarm-log", "reset-sequence"],
            "485 bus": ["alarm-log", "termination-resistor"],
            "alarm-log": ["failure-event"],
        },
        beam_width=2,
        max_depth=2,
    )

    assert out["schema"] == "mimirq.kg_agentic_beam_search.v1"
    assert out["seed_entities"] == ["watchdog", "485 bus"]
    assert out["paths"][0] == ["watchdog", "alarm-log", "failure-event"]
    assert out["paths"][1][0] == "485 bus"


def test_run_agentic_beam_search_returns_empty_paths_when_no_adjacency_exists() -> None:
    out = run_agentic_beam_search(
        query="Trace supplier drift.",
        topic_entities=["supplier"],
        adjacency={},
        beam_width=2,
        max_depth=2,
    )

    assert out["paths"] == []
    assert out["reason_codes"] == ["no_expandable_paths"]


def test_run_agentic_beam_search_respects_call_budget() -> None:
    out = run_agentic_beam_search(
        query="Trace why the watchdog alarm caused the 485 bus failure.",
        topic_entities=["watchdog", "485 bus"],
        adjacency={
            "watchdog": ["alarm-log", "reset-sequence"],
            "485 bus": ["alarm-log", "termination-resistor"],
            "alarm-log": ["failure-event"],
        },
        beam_width=2,
        max_depth=2,
        max_llm_calls=2,
    )

    assert out["budget"]["max_llm_calls"] == 2
    assert out["budget"]["llm_calls_used"] == 2
    assert out["budget"]["exhausted"] is True
    assert "llm_call_budget_exhausted" in out["reason_codes"]
    assert len(out["paths"]) <= 1
