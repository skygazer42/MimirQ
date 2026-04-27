from __future__ import annotations


def test_build_phoenix_trace_payload_from_rag_trace_bundle() -> None:
    from app.services.phoenix_adapter import build_phoenix_trace_payload
    from app.services.rag_metrics_dashboard import RagTraceBundle

    bundle = RagTraceBundle(
        enabled=True,
        path="/tmp/rag_metrics.jsonl",
        window_minutes=60,
        truncated=False,
        record_count=2,
        request_id="req-1",
        records=[
            {
                "event": "rag_trace",
                "request_id": "req-1",
                "ts_ms": 1000,
                "retrieval": {
                    "mode": "hybrid",
                    "elapsed_sec": 0.12,
                    "top_k": 8,
                    "profile": "long_context",
                },
                "citations_count": 2,
            },
            {
                "event": "rag_done",
                "request_id": "req-1",
                "ts_ms": 1200,
                "metrics": {
                    "generation_elapsed_sec": 0.25,
                    "context_tokens": 1800,
                },
                "route": "fast",
                "model_used": "gpt-5.4-mini",
            },
        ],
    )

    out = build_phoenix_trace_payload(bundle)

    assert out["schema"] == "mimirq.phoenix_adapter.v1"
    assert out["request_id"] == "req-1"
    assert len(out["spans"]) == 2
    names = {span["name"] for span in out["spans"]}
    assert names == {"retrieval", "generation"}
    retrieval = next(span for span in out["spans"] if span["name"] == "retrieval")
    assert retrieval["attributes"]["retrieval.mode"] == "hybrid"
    assert retrieval["attributes"]["retrieval.profile"] == "long_context"
    generation = next(span for span in out["spans"] if span["name"] == "generation")
    assert generation["attributes"]["generation.model_used"] == "gpt-5.4-mini"


def test_build_phoenix_trace_payload_noops_for_empty_bundle() -> None:
    from app.services.phoenix_adapter import build_phoenix_trace_payload
    from app.services.rag_metrics_dashboard import RagTraceBundle

    bundle = RagTraceBundle(
        enabled=True,
        path="/tmp/rag_metrics.jsonl",
        window_minutes=60,
        truncated=False,
        record_count=0,
        request_id="req-empty",
        records=[],
    )

    out = build_phoenix_trace_payload(bundle)

    assert out["spans"] == []
