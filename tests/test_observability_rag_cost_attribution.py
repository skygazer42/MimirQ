from __future__ import annotations

import json
import time
import uuid

import pytest
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


def test_observability_rag_cost_attribution(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_rag_cost_attribution
    from app.core.config import settings

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    now_ms = int(time.time() * 1000)

    metrics_path = tmp_path / "rag_metrics.jsonl"
    records = [
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "cost_attribution": {
                "schema": "mimirq.cost_attribution.v1",
                "llm": {
                    "model_used": "gpt-test",
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                    "source": "estimate",
                },
                "embeddings": {
                    "provider": "openai",
                    "model": "text-embedding-3-small",
                    "query_count": 2,
                    "query_chars": 120,
                    "query_tokens": 30,
                    "source": "estimate",
                },
                "retrieval": {"elapsed_sec": 0.25, "rerank_elapsed_sec": 0.1, "vector_backend": "milvus", "query_count": 2},
            },
        },
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "cost_attribution": {
                "schema": "mimirq.cost_attribution.v1",
                "llm": {
                    "model_used": "gpt-test",
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                    "total_tokens": 100,
                    "source": "estimate",
                },
                "embeddings": {
                    "provider": "openai",
                    "model": "text-embedding-3-small",
                    "query_count": 1,
                    "query_chars": 10,
                    "query_tokens": 10,
                    "source": "estimate",
                },
                "retrieval": {"elapsed_sec": 0.5, "rerank_elapsed_sec": None, "vector_backend": "milvus", "query_count": 1},
            },
        },
        # Different tenant should be ignored.
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(uuid.uuid4()),
            "cost_attribution": {
                "schema": "mimirq.cost_attribution.v1",
                "llm": {"model_used": "gpt-test", "prompt_tokens": 999, "completion_tokens": 999, "total_tokens": 1998},
                "embeddings": {"provider": "openai", "model": "text-embedding-3-small", "query_count": 1, "query_tokens": 999},
                "retrieval": {"elapsed_sec": 99.0, "vector_backend": "milvus", "query_count": 99},
            },
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
    app.get("/api/v1/observability/rag-metrics/cost-attribution")(get_rag_cost_attribution)
    client = TestClient(app)

    res = client.get("/api/v1/observability/rag-metrics/cost-attribution?window_minutes=60&max_bytes=5000000")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body.get("enabled") is True
    assert body.get("rag_trace_count") == 2

    assert body.get("llm_prompt_tokens") == 180
    assert body.get("llm_completion_tokens") == 70
    assert body.get("llm_total_tokens") == 250

    assert body.get("embed_query_tokens") == 40
    assert body.get("embed_query_chars") == 130
    assert body.get("embed_query_count") == 3

    assert float(body.get("retrieval_elapsed_avg_sec") or 0.0) > 0.35
    assert float(body.get("retrieval_elapsed_p95_sec") or 0.0) > 0.45

    assert float(body.get("rerank_elapsed_avg_sec") or 0.0) == pytest.approx(0.1)
