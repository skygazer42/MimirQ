from __future__ import annotations

import gzip
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


def test_observability_metrics_tail_export_redacted_gzip(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_rag_metrics_tail
    from app.core.config import settings

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    now_ms = int(time.time() * 1000)

    metrics_path = tmp_path / "rag_metrics.jsonl"
    records = [
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "question": "my email is user@example.com",
            "query_for_retrieval": "TOP_SECRET_QUERY",
            "citations_count": 1,
            "citations": [
                {
                    "chunk_id": "c1",
                    "document_id": "d1",
                    "snippet": "TOP_SECRET_SNIPPET",
                    "text": "TOP_SECRET_TEXT",
                }
            ],
            "retrieval": {"elapsed_sec": 0.1, "errors": []},
        },
        # rag_done can include structured_data / abstain_followup; must be stripped.
        {
            "event": "rag_done",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "request_id": "req-1",
            "metrics": {
                "structured_data": {"email": "user@example.com"},
                "abstain_followup": "please share your phone 13800138000",
                "elapsed_sec": 1.0,
            },
        },
        # Different tenant should be ignored.
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(other_tenant_id),
            "question": "OTHER_TENANT_TEXT",
            "citations_count": 0,
            "retrieval": {"elapsed_sec": 0.1, "errors": []},
        },
    ]
    metrics_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    monkeypatch.setattr(settings, "ENABLE_METRICS_LOG", True, raising=False)
    monkeypatch.setattr(settings, "METRICS_LOG_PATH", str(metrics_path), raising=False)
    # Simulate that the original metrics log may include text.
    monkeypatch.setattr(settings, "METRICS_LOG_INCLUDE_TEXT", True, raising=False)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/observability/rag-metrics/tail")(get_rag_metrics_tail)
    client = TestClient(app)

    res = client.get("/api/v1/observability/rag-metrics/tail?window_minutes=60&max_bytes=5000000")
    assert res.status_code == 200, res.text
    assert (res.headers.get("content-type") or "").startswith("application/gzip")

    payload = gzip.decompress(res.content).decode("utf-8")

    # Strip text fields even if original log contained them.
    assert "TOP_SECRET_QUERY" not in payload
    assert "TOP_SECRET_SNIPPET" not in payload
    assert "TOP_SECRET_TEXT" not in payload
    assert "OTHER_TENANT_TEXT" not in payload
    assert "query_for_retrieval" not in payload
    assert "structured_data" not in payload
    assert "abstain_followup" not in payload

    lines = [json.loads(line) for line in payload.splitlines() if (line or "").strip()]
    assert lines
    assert all(str(r.get("tenant_id")) == str(tenant_id) for r in lines if r.get("tenant_id") is not None)


def test_observability_metrics_tail_export_has_size_limit(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_rag_metrics_tail
    from app.core.config import settings

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    metrics_path = tmp_path / "rag_metrics.jsonl"
    metrics_path.write_text(json.dumps({"event": "rag_trace", "ts_ms": int(time.time() * 1000), "tenant_id": str(tenant_id)}))

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
    app.get("/api/v1/observability/rag-metrics/tail")(get_rag_metrics_tail)
    client = TestClient(app)

    # FastAPI Query validation should enforce an upper bound on max_bytes.
    res = client.get("/api/v1/observability/rag-metrics/tail?window_minutes=60&max_bytes=999999999")
    assert res.status_code == 422, res.text

