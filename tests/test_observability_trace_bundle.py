import hashlib
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


def _short_hash(text: str) -> str:
    raw = (text or "").encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


def test_observability_trace_bundle_export(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_rag_trace_bundle
    from app.core.config import settings

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    request_id = "req-123"
    now_ms = int(time.time() * 1000)

    question = "hi secret"
    query = "how to restart service"

    metrics_path = tmp_path / "rag_metrics.jsonl"
    records = [
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "request_id": request_id,
            "question": question,
            "query_for_retrieval": query,
            "citations_count": 1,
            "retrieval": {"elapsed_sec": 0.12, "errors": []},
            "citations": [
                {
                    "chunk_id": "c1",
                    "document_id": "d1",
                    "hit_type": "vector",
                    "retrieval_elapsed_sec": 0.12,
                    "extra_text": "SHOULD_NOT_LEAK",
                }
            ],
        },
        {
            "event": "rag_done",
            "ts_ms": now_ms + 1,
            "tenant_id": str(tenant_id),
            "request_id": request_id,
            "metrics": {
                "elapsed_sec": 0.5,
                "structured_data": {"leak": "SHOULD_NOT_LEAK"},
                "abstain_followup": "SHOULD_NOT_LEAK",
            },
        },
        # Different request_id should be ignored.
        {
            "event": "rag_trace",
            "ts_ms": now_ms,
            "tenant_id": str(tenant_id),
            "request_id": "req-other",
            "question_hash": _short_hash("other"),
            "citations_count": 0,
            "retrieval": {"elapsed_sec": 9.0, "errors": []},
            "citations": [],
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
    app.get("/api/v1/observability/rag-metrics/trace-bundle")(get_rag_trace_bundle)
    client = TestClient(app)

    res = client.get(
        f"/api/v1/observability/rag-metrics/trace-bundle?request_id={request_id}&window_minutes=60&max_bytes=5000000"
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body.get("request_id") == request_id
    items = body.get("records") or []
    assert len(items) == 2

    trace = next(x for x in items if x.get("event") == "rag_trace")
    assert "question" not in trace
    assert "query_for_retrieval" not in trace
    assert trace.get("question_hash") == _short_hash(question)
    assert trace.get("query_hash") == _short_hash(query)
    assert trace.get("citations") and "extra_text" not in trace["citations"][0]

    done = next(x for x in items if x.get("event") == "rag_done")
    assert "structured_data" not in (done.get("metrics") or {})
    assert "abstain_followup" not in (done.get("metrics") or {})


def test_observability_trace_bundle_404(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_rag_trace_bundle
    from app.core.config import settings

    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    metrics_path = tmp_path / "rag_metrics.jsonl"
    metrics_path.write_text(
        json.dumps({"event": "rag_trace", "tenant_id": str(tenant_id), "request_id": "x"}), encoding="utf-8"
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
    app.get("/api/v1/observability/rag-metrics/trace-bundle")(get_rag_trace_bundle)
    client = TestClient(app)

    res = client.get(
        "/api/v1/observability/rag-metrics/trace-bundle?request_id=missing&window_minutes=60&max_bytes=5000000"
    )
    assert res.status_code == 404
