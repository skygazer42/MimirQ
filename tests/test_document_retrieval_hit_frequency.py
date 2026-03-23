from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    payload = "\n".join(json.dumps(record) for record in records) + "\n"
    path.write_text(payload, encoding="utf-8")


def test_compute_document_retrieval_hit_frequency_returns_disabled_when_metrics_log_is_off(
    monkeypatch, tmp_path
):  # noqa: ANN001
    import app.services.document_retrieval_hit_frequency as service

    monkeypatch.setattr(service.settings, "ENABLE_METRICS_LOG", False, raising=False)
    monkeypatch.setattr(service.settings, "METRICS_LOG_PATH", str(tmp_path / "rag_metrics.jsonl"), raising=False)

    result = service.compute_document_retrieval_hit_frequency(
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert result["enabled"] is False
    assert result["available"] is False
    assert result["traces_scanned"] == 0
    assert result["traces_with_hits"] == 0
    assert result["citations_matched"] == 0
    assert result["unique_chunks_matched"] == 0
    assert result["hit_rate"] is None


def test_compute_document_retrieval_hit_frequency_counts_recent_matching_citations(
    monkeypatch, tmp_path
):  # noqa: ANN001
    import app.services.document_retrieval_hit_frequency as service

    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    other_document_id = uuid.uuid4()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    log_path = tmp_path / "rag_metrics.jsonl"

    def _ts(minutes_ago: int) -> int:
        return int((now.timestamp() - (minutes_ago * 60)) * 1000)

    _write_jsonl(
        log_path,
        [
            {
                "event": "rag_trace",
                "tenant_id": str(tenant_id),
                "ts_ms": _ts(10),
                "citations": [
                    {"document_id": str(document_id), "chunk_id": "chunk-1"},
                    {"document_id": str(document_id), "chunk_id": "chunk-2"},
                ],
            },
            {
                "event": "rag_trace",
                "tenant_id": str(tenant_id),
                "ts_ms": _ts(5),
                "citations": [
                    {"document_id": str(other_document_id), "chunk_id": "chunk-x"},
                    {"document_id": str(document_id), "chunk_id": "chunk-1"},
                ],
            },
            {
                "event": "rag_trace",
                "tenant_id": str(tenant_id),
                "ts_ms": _ts(180),
                "citations": [{"document_id": str(document_id), "chunk_id": "too-old"}],
            },
            {
                "event": "rag_trace",
                "tenant_id": str(other_tenant_id),
                "ts_ms": _ts(1),
                "citations": [{"document_id": str(document_id), "chunk_id": "wrong-tenant"}],
            },
            {
                "event": "other_event",
                "tenant_id": str(tenant_id),
                "ts_ms": _ts(1),
                "citations": [{"document_id": str(document_id), "chunk_id": "wrong-event"}],
            },
        ],
    )

    monkeypatch.setattr(service.settings, "ENABLE_METRICS_LOG", True, raising=False)
    monkeypatch.setattr(service.settings, "METRICS_LOG_PATH", str(log_path), raising=False)

    result = service.compute_document_retrieval_hit_frequency(
        tenant_id=tenant_id,
        document_id=document_id,
        window_minutes=60,
        max_bytes=5_000_000,
        now=now,
    )

    assert result["enabled"] is True
    assert result["available"] is True
    assert result["truncated"] is False
    assert result["traces_scanned"] == 2
    assert result["traces_with_hits"] == 2
    assert result["citations_matched"] == 3
    assert result["unique_chunks_matched"] == 2
    assert result["hit_rate"] == 1.0
