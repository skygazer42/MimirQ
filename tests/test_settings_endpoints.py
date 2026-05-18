from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def add(self, obj) -> None:  # noqa: ANN001
        return None

    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_settings_get_includes_url_ingest_and_governance(monkeypatch):  # noqa: ANN001
    import app.api.v1.settings as settings_module
    from app.api.v1.settings import get_settings
    from app.core.config import settings

    # Bypass dataset membership + role checks.
    monkeypatch.setattr(settings_module, "_ensure_settings_readable", lambda *_args, **_kwargs: None, raising=True)

    # Seed values that must round-trip through the response model.
    monkeypatch.setattr(settings, "CHUNK_MIN_CHARS", 42, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(settings, "RERANKER_PROVIDER", "cross_encoder", raising=False)
    monkeypatch.setattr(settings, "RERANKER_TOP_N", 24, raising=False)

    monkeypatch.setattr(settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_MAX_BYTES", 1234, raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_TIMEOUT_SEC", 5.5, raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False, raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_FOLLOW_REDIRECTS", True, raising=False)

    monkeypatch.setattr(settings, "GOVERNANCE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "GOVERNANCE_PII_ANONYMIZE", True, raising=False)
    monkeypatch.setattr(settings, "GOVERNANCE_SECRETS_REDACT", True, raising=False)
    monkeypatch.setattr(settings, "GOVERNANCE_QUARANTINE_ON_DROP", True, raising=False)
    monkeypatch.setattr(
        settings,
        "NAVIGATION_USER_VISIBLE_MODULES",
        "knowledgeGraph,reports,unknownModule",
        raising=False,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/settings")(get_settings)
    client = TestClient(app)

    res = client.get("/api/v1/settings")
    assert res.status_code == 200, res.text
    body = res.json()

    assert (body.get("rag") or {}).get("chunk_min_chars") == 42
    assert (body.get("rag") or {}).get("bm25_index_enabled") is False
    assert (body.get("rag") or {}).get("enable_reranker") is True
    assert (body.get("rag") or {}).get("reranker_provider") == "cross_encoder"
    assert (body.get("rag") or {}).get("reranker_top_n") == 24

    url_ingest = body.get("url_ingest") or {}
    assert url_ingest.get("enabled") is True
    assert url_ingest.get("max_bytes") == 1234
    assert abs(float(url_ingest.get("timeout_sec")) - 5.5) < 1e-6
    assert url_ingest.get("allow_private_ips") is False
    assert url_ingest.get("follow_redirects") is True

    governance = body.get("governance") or {}
    assert governance.get("enabled") is True
    assert governance.get("pii_anonymize") is True
    assert governance.get("secrets_redact") is True
    assert governance.get("quarantine_on_drop") is True

    paddlevl = body.get("paddle_vl") or {}
    assert paddlevl.get("pipeline_version") == "v1.5"
    assert paddlevl.get("mode") == "doc_parser"

    navigation = body.get("navigation") or {}
    assert navigation.get("user_visible_modules") == ["knowledgeGraph", "reports"]


def test_settings_put_persists_new_env_keys(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.settings as settings_module
    from app.api.v1.settings import update_settings
    from app.core.config import settings

    monkeypatch.setattr(settings_module, "_ensure_settings_writable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(settings_module, "ENV_FILE", tmp_path / "test.env", raising=True)

    # Ensure the runtime apply path sees a state transition for BM25.
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.put("/api/v1/settings")(update_settings)
    client = TestClient(app)

    payload = {
        "rag": {
            "chunk_size": 123,
            "chunk_overlap": 45,
            "chunk_min_chars": 67,
            "retrieval_top_k": 9,
            "similarity_threshold": 0.42,
            "default_parser_backend": "auto",
            "default_chunk_strategy": "langchain_recursive",
            "bm25_index_enabled": False,
            "enable_reranker": True,
            "reranker_provider": "cross_encoder",
            "reranker_top_n": 24,
        },
        "url_ingest": {
            "enabled": True,
            "max_bytes": 1000,
            "timeout_sec": 7.5,
            "allow_private_ips": False,
            "follow_redirects": False,
        },
        "governance": {
            "enabled": True,
            "pii_anonymize": True,
            "secrets_redact": True,
            "quarantine_on_drop": True,
        },
        "paddle_vl": {
            "api_url": "http://paddlevl.local/convert",
            "timeout_sec": 123,
            "pipeline_version": "v1.5",
            "mode": "doc_parser",
        },
        "navigation": {
            "user_visible_modules": ["knowledgeGraph", "graphSnapshots", "reports"],
        },
    }
    res = client.put("/api/v1/settings", json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("success") is True

    updated = set(body.get("updated_keys") or [])
    assert "CHUNK_MIN_CHARS" in updated
    assert "BM25_INDEX_ENABLED" in updated
    assert "ENABLE_RERANKER" in updated
    assert "RERANKER_PROVIDER" in updated
    assert "RERANKER_TOP_N" in updated
    assert "URL_INGEST_ENABLED" in updated
    assert "GOVERNANCE_ENABLED" in updated
    assert "PADDLE_VL_API_URL" in updated
    assert "PADDLE_VL_TIMEOUT_SEC" in updated
    assert "PADDLE_VL_PIPELINE_VERSION" in updated
    assert "PADDLE_VL_MODE" in updated
    assert "NAVIGATION_USER_VISIBLE_MODULES" in updated

    # Verify env file is written.
    env_text = (tmp_path / "test.env").read_text(encoding="utf-8")
    assert "CHUNK_MIN_CHARS=67" in env_text
    assert "BM25_INDEX_ENABLED=false" in env_text
    assert "ENABLE_RERANKER=true" in env_text
    assert "RERANKER_PROVIDER=cross_encoder" in env_text
    assert "RERANKER_TOP_N=24" in env_text
    assert "URL_INGEST_ENABLED=true" in env_text
    assert "URL_INGEST_MAX_BYTES=1000" in env_text
    assert "URL_INGEST_TIMEOUT_SEC=7.5" in env_text
    assert "GOVERNANCE_ENABLED=true" in env_text
    assert "GOVERNANCE_PII_ANONYMIZE=true" in env_text
    assert "GOVERNANCE_SECRETS_REDACT=true" in env_text
    assert "GOVERNANCE_QUARANTINE_ON_DROP=true" in env_text
    assert "PADDLE_VL_API_URL=http://paddlevl.local/convert" in env_text
    assert "PADDLE_VL_TIMEOUT_SEC=123" in env_text
    assert "PADDLE_VL_PIPELINE_VERSION=v1.5" in env_text
    assert "PADDLE_VL_MODE=doc_parser" in env_text
    assert "NAVIGATION_USER_VISIBLE_MODULES=knowledgeGraph,graphSnapshots,reports" in env_text

    # Verify runtime apply updated in-memory settings (best-effort).
    assert int(settings.CHUNK_MIN_CHARS) == 67
    assert bool(settings.BM25_INDEX_ENABLED) is False
    assert bool(settings.ENABLE_RERANKER) is True
    assert str(settings.RERANKER_PROVIDER) == "cross_encoder"
    assert int(settings.RERANKER_TOP_N) == 24
    assert bool(settings.URL_INGEST_ENABLED) is True
    assert int(settings.URL_INGEST_MAX_BYTES) == 1000
    assert abs(float(settings.URL_INGEST_TIMEOUT_SEC) - 7.5) < 1e-6
    assert bool(settings.GOVERNANCE_ENABLED) is True
    assert bool(settings.GOVERNANCE_PII_ANONYMIZE) is True
    assert bool(settings.GOVERNANCE_SECRETS_REDACT) is True
    assert bool(settings.GOVERNANCE_QUARANTINE_ON_DROP) is True
    assert str(settings.PADDLE_VL_API_URL) == "http://paddlevl.local/convert"
    assert int(settings.PADDLE_VL_TIMEOUT_SEC) == 123
    assert str(getattr(settings, "PADDLE_VL_PIPELINE_VERSION", "")) == "v1.5"
    assert str(getattr(settings, "PADDLE_VL_MODE", "")) == "doc_parser"
    assert str(getattr(settings, "NAVIGATION_USER_VISIBLE_MODULES", "")) == "knowledgeGraph,graphSnapshots,reports"


def test_settings_status_probes_paddlevl_health(monkeypatch):  # noqa: ANN001
    import app.api.v1.settings as settings_module
    from app.api.v1.settings import get_system_status
    from app.core.config import settings

    monkeypatch.setattr(settings_module, "_ensure_settings_readable", lambda *_args, **_kwargs: None, raising=True)

    # Enable paddle_vl and provide a convert endpoint.
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "http://paddlevl.local/convert", raising=False)
    monkeypatch.setattr(settings, "QIANFAN_OCR_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "QIANFAN_OCR_API_URL", "http://qianfan.local/convert", raising=False)

    # Avoid real DB/Milvus connectivity in unit tests.
    import app.core.database as db_module

    class _DummySession:  # noqa: D401
        def execute(self, *_args, **_kwargs):  # noqa: ANN001
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(db_module, "SessionLocal", lambda: _DummySession(), raising=True)

    import pymilvus

    monkeypatch.setattr(pymilvus.connections, "connect", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(pymilvus.connections, "disconnect", lambda *_args, **_kwargs: None, raising=True)

    async def _async_probe(*_args, **_kwargs):  # noqa: ANN001
        return ({"ok": True, "pipeline_version": "v1.5", "mode": "doc_parser"}, None)

    monkeypatch.setattr(settings_module, "_probe_http_json", _async_probe, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/settings/status")(get_system_status)
    client = TestClient(app)

    res = client.get("/api/v1/settings/status")
    assert res.status_code == 200, res.text
    body = res.json()

    parsers = body.get("parsers") or {}
    paddle = parsers.get("paddle_vl") or {}
    assert paddle.get("enabled") is True
    assert paddle.get("available") is True
    assert (paddle.get("health") or {}).get("pipeline_version") == "v1.5"

    qianfan = parsers.get("qianfan_ocr") or {}
    assert qianfan.get("enabled") is True
    assert qianfan.get("available") is True


def test_llm_api_base_defaults_follow_runtime_settings(monkeypatch):  # noqa: ANN001
    from app.api.v1.settings import LLMConfig, TestLLMRequest
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_API_BASE", "https://llm.example.test/v1", raising=False)

    llm_cfg = LLMConfig()
    llm_test_req = TestLLMRequest(api_key="k", model="m")

    assert llm_cfg.api_base == "https://llm.example.test/v1"
    assert llm_test_req.api_base == "https://llm.example.test/v1"


def test_settings_status_awaits_async_health_probe(monkeypatch):  # noqa: ANN001
    import app.api.v1.settings as settings_module
    from app.api.v1.settings import get_system_status
    from app.core.config import settings

    monkeypatch.setattr(settings_module, "_ensure_settings_readable", lambda *_args, **_kwargs: None, raising=True)

    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "http://paddlevl.local/convert", raising=False)

    async def _async_probe(*_args, **_kwargs):  # noqa: ANN001
        return ({"ok": True, "pipeline_version": "v1.6", "mode": "doc_parser"}, None)

    monkeypatch.setattr(settings_module, "_probe_http_json", _async_probe, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/settings/status")(get_system_status)
    client = TestClient(app)

    res = client.get("/api/v1/settings/status")
    assert res.status_code == 200, res.text
    body = res.json()

    paddle = (body.get("parsers") or {}).get("paddle_vl") or {}
    assert paddle.get("message") == "configured (v1.6, doc_parser)"
