import types

import pytest

from app.core.config import settings
from app.services import slo_snapshot_service


@pytest.mark.asyncio
async def test_build_slo_snapshot_falls_back_to_metrics_jsonl(monkeypatch):
    monkeypatch.setattr(settings, "PROMETHEUS_QUERY_BASE_URL", "", raising=False)

    def fake_summarize_rag_query_analytics(*, tenant_id, window_minutes, **_kwargs):
        if int(window_minutes) == 60:
            return types.SimpleNamespace(
                window_minutes=60,
                rag_trace_count=100,
                retrieval_p95_elapsed_sec=1.1,
                retrieval_p99_elapsed_sec=2.2,
                zero_hit_rate=0.1,
                timeseries={"errors": [1, 2]},
            )
        return types.SimpleNamespace(
            window_minutes=1440,
            rag_trace_count=200,
            retrieval_p95_elapsed_sec=1.5,
            retrieval_p99_elapsed_sec=3.0,
            zero_hit_rate=0.2,
            timeseries={"errors": [0, 4]},
        )

    monkeypatch.setattr(
        slo_snapshot_service,
        "summarize_rag_query_analytics",
        fake_summarize_rag_query_analytics,
        raising=True,
    )

    out = await slo_snapshot_service.build_slo_snapshot(tenant_id="t-1")
    assert out["schema"] == slo_snapshot_service.SLO_SNAPSHOT_SCHEMA_V1
    assert "generated_at" in out
    assert len(out["windows"]) == 2

    w1 = out["windows"][0]
    assert w1["window_minutes"] == 60
    assert w1["source"] == "metrics_jsonl"
    assert w1["retrieval_p95_elapsed_sec"] == pytest.approx(1.1)
    assert w1["retrieval_p99_elapsed_sec"] == pytest.approx(2.2)
    assert w1["zero_hit_rate"] == pytest.approx(0.1)
    assert w1["error_rate"] == pytest.approx(3.0 / 100.0)

    w24 = out["windows"][1]
    assert w24["window_minutes"] == 1440
    assert w24["source"] == "metrics_jsonl"
    assert w24["error_rate"] == pytest.approx(4.0 / 200.0)

