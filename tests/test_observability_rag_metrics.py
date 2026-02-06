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


def test_observability_rag_metrics_summary(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_rag_metrics_summary
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
            "retrieval": {
                "mode": "hybrid",
                "errors": [],
                "per_query": [
                    {
                        "kind": "main",
                        "query_chars": 12,
                        "elapsed_sec": 0.12,
                        "ok": True,
                        "retriever_debug": {
                            "requested_k": 5,
                            "search_k": 20,
                            "overfetch_enabled": True,
                            "enrich_pass1": {"filtered_acl": 2, "output_results": 7},
                        },
                    }
                ],
            },
            "citations": [
                {"hit_type": "vector", "retrieval_elapsed_sec": 0.12, "rerank_elapsed_sec": 0.0},
                {"hit_type": "keyword", "retrieval_elapsed_sec": 0.12, "rerank_elapsed_sec": 0.0},
            ],
        },
        {
            "event": "reranker_api",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "elapsed_sec": 0.45,
            "cache_hits": 1,
            "cache_misses": 1,
        },
        # Different tenant should be ignored.
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(uuid.uuid4()),
            "retrieval": {"mode": "vector", "errors": ["x"]},
            "citations": [{"hit_type": "vector", "retrieval_elapsed_sec": 9.0}],
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
    app.get("/api/v1/observability/rag-metrics/summary")(get_rag_metrics_summary)
    client = TestClient(app)

    res = client.get("/api/v1/observability/rag-metrics/summary?window_minutes=60&max_bytes=5000000")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body.get("enabled") is True
    assert body.get("rag_trace_count") == 1
    assert body.get("reranker_api_count") == 1
    assert (body.get("retrieval_mode_counts") or {}).get("hybrid") == 1
    assert (body.get("hit_type_counts") or {}).get("vector") == 1
    assert (body.get("hit_type_counts") or {}).get("keyword") == 1

    assert body.get("retriever_overfetch_count") == 1
    assert body.get("retriever_overfetch_avg_ratio") == 4.0
    assert body.get("retriever_filtered_acl_total") == 2
