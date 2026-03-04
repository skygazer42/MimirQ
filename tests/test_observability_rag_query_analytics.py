from __future__ import annotations

import json
import time
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def commit(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def test_observability_rag_query_analytics(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_rag_query_analytics
    from app.core.config import settings

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *args, **kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    now_ms = int(time.time() * 1000)

    metrics_path = tmp_path / "rag_metrics.jsonl"
    records = [
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "query_hash": "aaa",
            "citations_count": 0,
            "retrieval": {"elapsed_sec": 3.0, "errors": ["main:timeout"]},
        },
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "query_hash": "aaa",
            "citations_count": 0,
            "retrieval": {"elapsed_sec": 4.0, "errors": []},
        },
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "query_hash": "bbb",
            "citations_count": 2,
            "retrieval": {"elapsed_sec": 0.2, "errors": []},
        },
        # Different tenant should be ignored.
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(uuid.uuid4()),
            "query_hash": "ccc",
            "citations_count": 0,
            "retrieval": {"elapsed_sec": 99.0, "errors": []},
        },
    ]
    metrics_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    monkeypatch.setattr(settings, "ENABLE_METRICS_LOG", True, raising=False)
    monkeypatch.setattr(settings, "METRICS_LOG_PATH", str(metrics_path), raising=False)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/observability/rag-metrics/query-analytics")(get_rag_query_analytics)
    client = TestClient(app)

    res = client.get(
        "/api/v1/observability/rag-metrics/query-analytics?window_minutes=60&slow_threshold_sec=2.0&max_bytes=5000000"
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body.get("enabled") is True
    assert body.get("rag_trace_count") == 3
    assert body.get("unique_query_hashes") == 2

    assert body.get("zero_hit_count") == 2
    assert body.get("zero_hit_rate") == (2 / 3)

    top_zero = body.get("top_zero_hit_queries") or []
    assert top_zero and top_zero[0]["query_hash"] == "aaa"
    assert top_zero[0]["count"] == 2

    assert body.get("slow_count") == 2
    top_slow = body.get("top_slow_queries") or []
    assert top_slow and top_slow[0]["query_hash"] == "aaa"
    assert top_slow[0]["count"] == 2

    # With retrieval elapsed values [0.2, 3.0, 4.0]
    assert float(body.get("retrieval_p95_elapsed_sec") or 0) > 3.8

    error_kind_counts = body.get("error_kind_counts") or {}
    assert error_kind_counts.get("main") == 1


def test_observability_rag_query_analytics_anomalies(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_rag_query_analytics
    from app.core.config import settings

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *args, **kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    now_ms = int(time.time() * 1000)
    base_minute_ms = (now_ms // 60_000) * 60_000

    # Build a baseline (60 min) with low rates, then a current window (5 min) with spikes.
    def _ts(minute_offset: int) -> int:
        return base_minute_ms + (minute_offset * 60_000) + 123

    def _rag_trace(*, ts_ms: int, citations_count: int, error_kind: str | None) -> dict:
        retrieval = {"elapsed_sec": 0.1, "errors": []}
        if error_kind:
            retrieval["errors"] = [f"{error_kind}:boom"]
        return {
            "event": "rag_trace",
            "ts_ms": ts_ms,
            "tenant_id": str(tenant_id),
            "query_hash": "aaa",
            "citations_count": citations_count,
            "retrieval": retrieval,
        }

    records: list[dict] = []

    # Baseline minutes: -64..-5 (low zero-hit, low errors).
    for m in range(-64, -4):
        ts = _ts(m)
        # 5 requests/minute; 0 zero-hit; 0 errors.
        for _ in range(5):
            records.append(_rag_trace(ts_ms=ts, citations_count=1, error_kind=None))

    # Current minutes: -4..0 (high zero-hit, high errors).
    for m in range(-4, 1):
        ts = _ts(m)
        # 5 requests/minute; 4 zero-hit; 4 errors.
        records.append(_rag_trace(ts_ms=ts, citations_count=1, error_kind=None))
        for _ in range(4):
            records.append(_rag_trace(ts_ms=ts, citations_count=0, error_kind="main"))

    metrics_path = tmp_path / "rag_metrics.jsonl"
    metrics_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    monkeypatch.setattr(settings, "ENABLE_METRICS_LOG", True, raising=False)
    monkeypatch.setattr(settings, "METRICS_LOG_PATH", str(metrics_path), raising=False)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/observability/rag-metrics/query-analytics")(get_rag_query_analytics)
    client = TestClient(app)

    res = client.get("/api/v1/observability/rag-metrics/query-analytics?window_minutes=120&slow_threshold_sec=2.0")
    assert res.status_code == 200, res.text
    body = res.json()

    anomalies = body.get("anomalies")
    assert isinstance(anomalies, list)
    keys = {a.get("key") for a in anomalies if isinstance(a, dict)}
    assert "rag.zero_hit_rate.spike" in keys
    assert "rag.error_rate.spike" in keys

    error_anomaly = next(a for a in anomalies if a.get("key") == "rag.error_rate.spike")
    extra = error_anomaly.get("extra") or {}
    assert extra.get("top_error_kind") == "main"
