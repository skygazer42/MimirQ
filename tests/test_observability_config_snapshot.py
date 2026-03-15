from __future__ import annotations

import json
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


def test_observability_config_snapshot_redacts_and_fingerprints(monkeypatch):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import get_ops_config_snapshot
    from app.core.config import settings

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    # Seed a few settings (including secrets) to validate redaction.
    monkeypatch.setattr(settings, "LLM_API_KEY", "sk-test-1234567890abcdef", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "emb-test-abcdef1234567890", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://user:pass@db.example.com:5432/mimirq", raising=False)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://:redispass@redis.example.com:6379/0", raising=False)
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(settings, "LLM_API_BASE", "https://api.openai.com/v1", raising=False)
    monkeypatch.setattr(settings, "LLM_MODEL", "gpt-4o-mini", raising=False)
    monkeypatch.setattr(settings, "PROMETHEUS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ENABLE_METRICS_LOG", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 123, raising=False)

    tenant_id = uuid.uuid4()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/observability/config/snapshot")(get_ops_config_snapshot)
    client = TestClient(app)

    res1 = client.get("/api/v1/observability/config/snapshot")
    assert res1.status_code == 200, res1.text
    body1 = res1.json()

    assert body1.get("schema") == "mimirq.ops_config_snapshot.v1"
    assert isinstance(body1.get("fingerprint"), str) and len(body1.get("fingerprint") or "") >= 16
    assert isinstance(body1.get("config"), dict)

    # Fingerprint should be stable for unchanged config (no timestamps baked in).
    res2 = client.get("/api/v1/observability/config/snapshot")
    assert res2.status_code == 200, res2.text
    body2 = res2.json()
    assert body2.get("fingerprint") == body1.get("fingerprint")

    # Redaction checks: raw secrets must not appear.
    raw_secrets = [
        "sk-test-1234567890abcdef",
        "emb-test-abcdef1234567890",
        "pass@db.example.com",
        "redispass@redis.example.com",
    ]
    dumped = json.dumps(body1, ensure_ascii=False)
    for raw in raw_secrets:
        assert raw not in dumped

    llm = (body1.get("config") or {}).get("llm") or {}
    assert llm.get("api_key_masked") and "***" in str(llm.get("api_key_masked"))

    retrieval_fp = (body1.get("config") or {}).get("retrieval_fingerprint") or {}
    retrieval_cfg = retrieval_fp.get("config") or {}
    assert retrieval_cfg.get("colbert_enabled") is True
    assert retrieval_cfg.get("colbert_max_docs") == 123
