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

