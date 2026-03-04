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


def test_observability_trace_bundle_diff(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_rag_trace_bundle_diff
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
            "request_id": "req-a",
            "citations_count": 2,
            "retrieval": {
                "mode": "vector",
                "requested_mode": "auto",
                "auto_routed": True,
                "profile": "default",
                "retrieval_config_hash": "hash-a",
                "top_k": 5,
                "alpha": 0.1,
                "enable_reranker": False,
                "reranker_provider": "",
                "reranker_top_n": 0,
                "query_parallelism": 2,
                "query_count": 1,
                "elapsed_sec": 0.12,
                "errors": ["timeout: backend"],
            },
            "route": {"model_route": "r1", "model_used": "m1", "reason": "test"},
        },
        {
            "event": "rag_done",
            "ts_ms": now_ms + 1,
            "tenant_id": str(tenant_id),
            "request_id": "req-a",
            "vector_backend": "milvus",
            "route": "r1",
            "model_used": "m1",
            "retrieval_mode": "vector",
            "metrics": {"elapsed_sec": 0.5},
        },
        {
            "event": "rag_trace",
            "ts_ms": now_ms + 2,
            "tenant_id": str(tenant_id),
            "request_id": "req-b",
            "citations_count": 0,
            "retrieval": {
                "mode": "hybrid",
                "requested_mode": "hybrid",
                "auto_routed": False,
                "profile": "precision",
                "retrieval_config_hash": "hash-b",
                "top_k": 10,
                "alpha": 0.6,
                "enable_reranker": True,
                "reranker_provider": "cohere",
                "reranker_top_n": 20,
                "query_parallelism": 4,
                "query_count": 3,
                "elapsed_sec": 1.2345,
                "errors": ["http_429: upstream"],
            },
            "route": {"model_route": "r2", "model_used": "m2", "reason": "test"},
        },
        {
            "event": "rag_done",
            "ts_ms": now_ms + 3,
            "tenant_id": str(tenant_id),
            "request_id": "req-b",
            "vector_backend": "chroma",
            "route": "r2",
            "model_used": "m2",
            "retrieval_mode": "hybrid",
            "metrics": {"elapsed_sec": 2.0},
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
    app.get("/api/v1/observability/rag-metrics/trace-bundle/diff")(get_rag_trace_bundle_diff)
    client = TestClient(app)

    res = client.get(
        "/api/v1/observability/rag-metrics/trace-bundle/diff"
        "?request_id_a=req-a&request_id_b=req-b&window_minutes=60&max_bytes=5000000"
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body.get("schema") == "mimirq.rag_trace_bundle_diff.v1"
    assert body.get("request_id_a") == "req-a"
    assert body.get("request_id_b") == "req-b"

    summary_a = body.get("summary_a") or {}
    summary_b = body.get("summary_b") or {}
    assert summary_a.get("retrieval_config_hash") == "hash-a"
    assert summary_b.get("retrieval_config_hash") == "hash-b"
    assert summary_a.get("retrieval_mode") == "vector"
    assert summary_b.get("retrieval_mode") == "hybrid"
    assert summary_a.get("citations_count") == 2
    assert summary_b.get("citations_count") == 0

    changed_keys = {it.get("key") for it in (body.get("diff") or []) if isinstance(it, dict)}
    assert "retrieval_config_hash" in changed_keys
    assert "retrieval_mode" in changed_keys
    assert "citations_count" in changed_keys
    assert "retrieval_error_kinds" in changed_keys


def test_observability_trace_bundle_diff_404(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_rag_trace_bundle_diff
    from app.core.config import settings

    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *args, **kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    metrics_path = tmp_path / "rag_metrics.jsonl"
    metrics_path.write_text(
        json.dumps({"event": "rag_trace", "tenant_id": str(tenant_id), "request_id": "req-a", "citations_count": 1}),
        encoding="utf-8",
    )

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
    app.get("/api/v1/observability/rag-metrics/trace-bundle/diff")(get_rag_trace_bundle_diff)
    client = TestClient(app)

    res = client.get(
        "/api/v1/observability/rag-metrics/trace-bundle/diff"
        "?request_id_a=req-a&request_id_b=req-missing&window_minutes=60&max_bytes=5000000"
    )
    assert res.status_code == 404

