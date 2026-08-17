import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.services import document_retrieval_hit_frequency, lineage_service, online_eval_service


def _write_jsonl(path, records: list[object]) -> None:
    path.write_text(
        "\n".join(item if isinstance(item, str) else json.dumps(item) for item in records) + "\n",
        encoding="utf-8",
    )


def test_jsonl_tail_readers_preserve_invalid_line_and_object_filtering(tmp_path) -> None:
    path = tmp_path / "metrics.jsonl"
    _write_jsonl(path, ["not-json", {"id": 1}, ["not", "an", "object"], {"id": 2}])

    assert document_retrieval_hit_frequency._read_jsonl_tail(path, max_bytes=10_000) == (
        [{"id": 1}, {"id": 2}],
        False,
    )
    assert online_eval_service._read_jsonl_tail(path, max_bytes=10_000) == (
        [{"id": 1}, {"id": 2}],
        False,
    )
    assert lineage_service._read_jsonl_tail(path, max_bytes=10_000) == [{"id": 1}, {"id": 2}]


def test_compute_document_retrieval_hit_frequency_preserves_filtering_and_counts(
    monkeypatch,
    tmp_path,
) -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    now = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    current_ms = int(now.timestamp() * 1000)
    path = tmp_path / "metrics.jsonl"
    _write_jsonl(
        path,
        [
            {"event": "other", "tenant_id": str(tenant_id), "ts_ms": current_ms},
            {"event": "rag_trace", "tenant_id": str(uuid4()), "ts_ms": current_ms},
            {
                "event": "rag_trace",
                "tenant_id": str(tenant_id),
                "ts_ms": int((now - timedelta(hours=2)).timestamp() * 1000),
            },
            {"event": "rag_trace", "tenant_id": str(tenant_id), "ts_ms": current_ms, "citations": []},
            {
                "event": "rag_trace",
                "tenant_id": str(tenant_id),
                "ts_ms": current_ms,
                "citations": [
                    {"document_id": str(document_id), "chunk_id": "chunk-a"},
                    {"document_id": str(document_id), "chunk_id": "chunk-a"},
                    {"document_id": str(uuid4()), "chunk_id": "other"},
                ],
            },
            {
                "event": "rag_trace",
                "tenant_id": str(tenant_id),
                "ts_ms": current_ms,
                "citations": [{"document_id": str(document_id), "chunk_id": "chunk-b"}],
            },
        ],
    )
    monkeypatch.setattr(document_retrieval_hit_frequency.settings, "ENABLE_METRICS_LOG", True)
    monkeypatch.setattr(document_retrieval_hit_frequency.settings, "METRICS_LOG_PATH", str(path))

    summary = document_retrieval_hit_frequency.compute_document_retrieval_hit_frequency(
        tenant_id=tenant_id,
        document_id=document_id,
        window_minutes=60,
        now=now,
    )

    assert summary["available"] is True
    assert summary["traces_scanned"] == 3
    assert summary["traces_with_hits"] == 2
    assert summary["citations_matched"] == 3
    assert summary["unique_chunks_matched"] == 2
    assert summary["hit_rate"] == 0.6667


def test_summarize_chunk_retrieval_usage_preserves_hit_order_and_mode_counts() -> None:
    tenant_id = uuid4()
    chunk_id = uuid4()
    now = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    current_ms = int(now.timestamp() * 1000)
    records = [
        {
            "event": "rag_trace",
            "tenant_id": str(tenant_id),
            "request_id": "older",
            "ts_ms": current_ms - 2_000,
            "retrieval": {"mode": "vector"},
            "citations": [{"chunk_id": str(chunk_id), "document_id": "doc-2"}],
        },
        {
            "event": "rag_trace",
            "tenant_id": str(tenant_id),
            "request_id": "newer",
            "conversation_id": "conversation-1",
            "ts_ms": current_ms - 1_000,
            "retrieval": {"mode": "hybrid", "requested_mode": "auto"},
            "citations": [
                {"chunk_id": str(chunk_id), "document_id": "doc-1", "page_number": "2"},
                {"chunk_id": str(chunk_id), "document_id": "doc-1", "chunk_index": 3},
            ],
        },
        {
            "event": "rag_trace",
            "tenant_id": str(tenant_id),
            "request_id": "no-hit",
            "ts_ms": current_ms,
            "citations": [{"chunk_id": str(uuid4())}],
        },
    ]

    summary = lineage_service.summarize_chunk_retrieval_usage_from_records(
        records,
        tenant_id=tenant_id,
        chunk_id=chunk_id,
        now=now,
        max_hits=3,
    )

    assert summary["traces_scanned"] == 3
    assert summary["traces_with_hits"] == 2
    assert summary["citations_matched"] == 3
    assert summary["request_ids"] == ["newer", "older"]
    assert summary["retrieval_modes"] == {"hybrid": 1, "vector": 1}
    assert [hit["request_id"] for hit in summary["hits"]] == ["newer", "newer", "older"]
    assert summary["last_seen_ts_ms"] == current_ms - 1_000


def test_summarize_online_quality_preserves_buckets_averages_and_alerts(
    monkeypatch,
    tmp_path,
) -> None:
    path = tmp_path / "metrics.jsonl"
    tenant_id = "tenant-1"
    _write_jsonl(
        path,
        [
            {
                "event": "online_eval",
                "tenant_id": tenant_id,
                "ts_ms": 900_000,
                "faithfulness_det": 0.5,
                "chunk_utilization": 0.1,
            },
            {
                "event": "online_eval",
                "tenant_id": tenant_id,
                "ts_ms": 950_000,
                "faithfulness_det": 0.7,
                "chunk_utilization": 0.3,
            },
            {"event": "online_eval", "tenant_id": "other", "ts_ms": 950_000},
            {"event": "other", "tenant_id": tenant_id, "ts_ms": 950_000},
        ],
    )
    monkeypatch.setattr(online_eval_service.settings, "ENABLE_METRICS_LOG", True)
    monkeypatch.setattr(online_eval_service.settings, "ONLINE_EVAL_ENABLED", True)
    monkeypatch.setattr(online_eval_service.settings, "METRICS_LOG_PATH", str(path))
    monkeypatch.setattr(online_eval_service.settings, "ONLINE_EVAL_ALERT_MIN_SAMPLES_PER_BUCKET", 2)
    monkeypatch.setattr(online_eval_service.settings, "ONLINE_EVAL_ALERT_FAITHFULNESS_DET_MIN", 0.7)
    monkeypatch.setattr(online_eval_service.settings, "ONLINE_EVAL_ALERT_CHUNK_UTILIZATION_MIN", 0.25)
    monkeypatch.setattr(online_eval_service.time, "time", lambda: 1_000.0)

    summary = online_eval_service.summarize_online_quality(
        tenant_id=tenant_id,
        window_minutes=60,
        bucket_minutes=5,
    )

    assert summary.record_count == 4
    assert summary.sample_count == 2
    assert summary.faithfulness_det_avg == 0.6
    assert summary.chunk_utilization_avg == 0.2
    assert summary.timeseries == {
        "ts_ms": [900_000],
        "samples": [2],
        "faithfulness_det_avg": [0.6],
        "chunk_utilization_avg": [0.2],
    }
    assert [(alert["metric"], alert["value"]) for alert in summary.alerts] == [
        ("faithfulness_det", 0.6),
        ("chunk_utilization", 0.2),
    ]
