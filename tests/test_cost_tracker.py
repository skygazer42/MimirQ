from __future__ import annotations

import pytest

from app.core.cost_tracker import (
    COST_EVENTS_TOTAL,
    COST_TOKENS_TOTAL,
    COST_USD_TOTAL,
    build_cost_event,
    record_cost_event,
    summarize_cost_events,
)


def test_build_cost_event_normalizes_tokens_and_cost_fields() -> None:
    event = build_cost_event(
        provider="openai",
        model="gpt-4.1-mini",
        input_tokens=120,
        output_tokens=30,
        cost_usd=0.0042,
        tenant_id="tenant-a",
        dataset_id="dataset-a",
    )

    assert event["schema"] == "mimirq.cost_event.v1"
    assert event["provider"] == "openai"
    assert event["model"] == "gpt-4.1-mini"
    assert event["input_tokens"] == 120
    assert event["output_tokens"] == 30
    assert event["total_tokens"] == 150
    assert event["cost_usd"] == 0.0042
    assert event["tenant_id"] == "tenant-a"
    assert event["dataset_id"] == "dataset-a"


def test_summarize_cost_events_aggregates_totals_and_provider_breakdown() -> None:
    summary = summarize_cost_events(
        [
            build_cost_event(
                provider="openai",
                model="gpt-4.1-mini",
                input_tokens=120,
                output_tokens=30,
                cost_usd=0.0042,
                tenant_id="tenant-a",
            ),
            build_cost_event(
                provider="openai",
                model="gpt-4.1-mini",
                input_tokens=80,
                output_tokens=20,
                cost_usd=0.0028,
                tenant_id="tenant-a",
            ),
            build_cost_event(
                provider="anthropic",
                model="claude-3.5-haiku",
                input_tokens=50,
                output_tokens=10,
                cost_usd=0.0015,
                tenant_id="tenant-b",
            ),
        ]
    )

    assert summary["schema"] == "mimirq.cost_summary.v1"
    assert summary["events"] == 3
    assert summary["total_tokens"] == 310
    assert summary["total_cost_usd"] == pytest.approx(0.0085)
    assert summary["by_provider"] == {
        "anthropic": {"events": 1, "total_tokens": 60, "total_cost_usd": 0.0015},
        "openai": {"events": 2, "total_tokens": 250, "total_cost_usd": 0.007},
    }
    assert summary["by_tenant"] == {
        "tenant-a": {"events": 2, "total_tokens": 250, "total_cost_usd": 0.007},
        "tenant-b": {"events": 1, "total_tokens": 60, "total_cost_usd": 0.0015},
    }


def test_record_cost_event_emits_metrics_payload_and_updates_prometheus(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, object]] = []

    def _fake_log_metrics(payload: dict[str, object]) -> None:
        captured.append(dict(payload))

    monkeypatch.setattr("app.core.cost_tracker.log_metrics", _fake_log_metrics, raising=True)

    labels = {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "tenant_id": "tenant-a",
        "stage": "answer",
    }
    events_before = COST_EVENTS_TOTAL.labels(**labels)._value.get()
    tokens_before = COST_TOKENS_TOTAL.labels(**labels)._value.get()
    cost_before = COST_USD_TOTAL.labels(**labels)._value.get()

    event = record_cost_event(
        provider="openai",
        model="gpt-4.1-mini",
        input_tokens=120,
        output_tokens=30,
        cost_usd=0.0042,
        tenant_id="tenant-a",
        dataset_id="dataset-a",
        request_id="req-1",
        stage="answer",
    )

    assert event["total_tokens"] == 150
    assert captured == [
        {
            "event": "cost_event",
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "cost_usd": 0.0042,
            "tenant_id": "tenant-a",
            "dataset_id": "dataset-a",
            "request_id": "req-1",
            "stage": "answer",
        }
    ]
    assert COST_EVENTS_TOTAL.labels(**labels)._value.get() == pytest.approx(events_before + 1)
    assert COST_TOKENS_TOTAL.labels(**labels)._value.get() == pytest.approx(tokens_before + 150)
    assert COST_USD_TOTAL.labels(**labels)._value.get() == pytest.approx(cost_before + 0.0042)
