import asyncio
import datetime
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.requests import Request

if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc


def _make_request(*, headers: list[tuple[bytes, bytes]] | None = None, client_host: str = "198.51.100.7") -> Request:
    scope = {
        "type": "http",
        "headers": headers or [],
        "client": (client_host, 1234),
        "state": {},
    }
    request = Request(scope)
    request.state.request_id = "req-state"
    return request


def test_apply_runtime_settings_preserves_storage_reset_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import health as health_api
    from app.api.v1 import settings as settings_api
    from app.storage.object import factory as object_factory
    from app.storage.object import minio as minio_module

    calls: list[str] = []

    monkeypatch.setattr(object_factory, "reset_object_store_cache", lambda: calls.append("reset_cache"), raising=True)
    monkeypatch.setattr(
        minio_module,
        "minio_service",
        SimpleNamespace(reset_runtime_state=lambda: calls.append("reset_minio")),
        raising=True,
    )
    monkeypatch.setattr(health_api, "invalidate_ready_cache", lambda: calls.append("invalidate_ready"), raising=True)

    settings_api._apply_runtime_settings(
        {
            "MINIO_ENDPOINT": "minio.example.test:9000",
            "OBJECT_STORAGE_ENDPOINT": "s3.example.test:443",
        },
        ["MINIO_ENDPOINT", "OBJECT_STORAGE_ENDPOINT"],
    )

    assert calls == ["reset_cache", "reset_minio", "invalidate_ready"]


def test_update_settings_preserves_write_apply_and_reset_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import settings as settings_api

    calls: list[str] = []
    db = SimpleNamespace(commit=lambda: calls.append("db_commit"))
    request = _make_request(
        headers=[
            (b"x-request-id", b"req-header"),
            (b"user-agent", b"pytest"),
        ]
    )

    monkeypatch.setattr(settings_api, "_ensure_settings_writable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(settings_api, "_env_file_lock", lambda: nullcontext(), raising=True)
    monkeypatch.setattr(settings_api, "read_env_file", lambda: {}, raising=True)
    monkeypatch.setattr(
        settings_api,
        "write_env_file",
        lambda env_vars: calls.append(("write_env_file", dict(env_vars))),
        raising=True,
    )
    monkeypatch.setattr(
        settings_api,
        "_apply_runtime_settings",
        lambda env_vars, updated_keys: calls.append(("apply_runtime", dict(env_vars), list(updated_keys))),
        raising=True,
    )

    def _audit_log_event(_db, **kwargs):
        calls.append(("audit_log_event", kwargs))

    def _reset_rag_engine():
        calls.append("reset_rag_engine")

    monkeypatch.setitem(sys.modules, "app.services.audit_log_service", SimpleNamespace(audit_log_event=_audit_log_event))
    monkeypatch.setitem(sys.modules, "app.rag.engine", SimpleNamespace(reset_rag_engine=_reset_rag_engine))

    result = settings_api.update_settings(
        settings_api.UpdateSettingsRequest(
            llm=settings_api.LLMConfig(
                api_key="llm-secret",
                api_base="https://llm.example.test/v1",
                model="gpt-5.4-mini",
                temperature=0.25,
                timeout=45,
                max_retries=5,
            )
        ),
        request,
        tenant_id=uuid4(),
        account_id="owner",
        db=db,
    )

    assert result == {
        "success": True,
        "message": "配置已保存，大多数修改会影响后续请求；外部解析器仍需对应服务已启动。",
        "updated_keys": [
            "LLM_API_KEY",
            "LLM_API_BASE",
            "LLM_MODEL",
            "LLM_TEMPERATURE",
            "LLM_TIMEOUT",
            "LLM_MAX_RETRIES",
        ],
    }
    assert [entry if isinstance(entry, str) else entry[0] for entry in calls] == [
        "write_env_file",
        "audit_log_event",
        "db_commit",
        "apply_runtime",
        "reset_rag_engine",
    ]
    assert calls[0][1] == {
        "LLM_API_KEY": "llm-secret",
        "LLM_API_BASE": "https://llm.example.test/v1",
        "LLM_MODEL": "gpt-5.4-mini",
        "LLM_TEMPERATURE": "0.25",
        "LLM_TIMEOUT": "45",
        "LLM_MAX_RETRIES": "5",
    }
    assert calls[1][1]["request_id"] == "req-header"
    assert calls[1][1]["ip"] == "198.51.100.7"
    assert calls[1][1]["user_agent"] == "pytest"
    assert calls[1][1]["details"] == {"updated_keys": result["updated_keys"]}
    assert calls[2] == "db_commit"
    assert calls[3][1] == calls[0][1]
    assert calls[3][2] == result["updated_keys"]


def test_get_system_status_reports_parser_health_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import settings as settings_api
    from app.core.config import settings

    class _Session:
        def execute(self, query):
            assert query == "SELECT 1"

        def close(self):
            pass

    class _Connections:
        def connect(self, **kwargs):
            assert kwargs["alias"] == "status_check"

        def disconnect(self, alias):
            assert alias == "status_check"

    async def _probe_http_json(url: str, *, timeout_sec: float = 0.6):
        if "qianfan.example.test" in url:
            return {"ok": False, "reason": "upstream-down"}, None
        if "paddlevl.example.test" in url:
            return {"ok": True, "pipeline_version": "v2", "mode": "doc_parser"}, None
        return None, "unreachable"

    def _find_spec(name: str):
        installed = {"markitdown", "app.deepdoc.parser"}
        return object() if name in installed else None

    monkeypatch.setattr(settings_api, "_ensure_settings_readable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(settings_api, "_probe_http_json", _probe_http_json, raising=True)
    monkeypatch.setattr(settings_api.importlib.util, "find_spec", _find_spec, raising=True)
    monkeypatch.setattr("app.core.database.SessionLocal", lambda: _Session(), raising=True)
    monkeypatch.setitem(sys.modules, "pymilvus", SimpleNamespace(connections=_Connections()))
    monkeypatch.setitem(sys.modules, "sqlalchemy", SimpleNamespace(text=lambda query: query))
    monkeypatch.setattr(
        "app.parsing.utils.cli.resolve_cli_command",
        lambda command: f"/usr/bin/{command}",
        raising=True,
    )
    monkeypatch.setattr(
        "app.parsing.parsers.magic_pdf_parser.resolve_magicpdf_models_dir",
        lambda _value: "/models/magicpdf",
        raising=True,
    )

    monkeypatch.setattr(settings, "LLM_API_KEY", "llm-key", raising=False)
    monkeypatch.setattr(settings, "LLM_MODEL", "gpt-5.4-mini", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "text-embedding-3-small", raising=False)
    monkeypatch.setattr(settings, "MILVUS_HOST", "milvus.example.test", raising=False)
    monkeypatch.setattr(settings, "MILVUS_PORT", 19530, raising=False)
    monkeypatch.setattr(settings, "MILVUS_USER", "", raising=False)
    monkeypatch.setattr(settings, "MILVUS_PASSWORD", "", raising=False)
    monkeypatch.setattr(settings, "MARKITDOWN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PANDOC_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PANDOC_CLI", "pandoc", raising=False)
    monkeypatch.setattr(settings, "LIBREOFFICE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LIBREOFFICE_CLI", "soffice", raising=False)
    monkeypatch.setattr(settings, "DEEPDOC_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "DEEPSEEK_OCR_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SILICONFLOW_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "QIANFAN_OCR_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "QIANFAN_OCR_API_URL", "https://qianfan.example.test/convert", raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_API_URL", "https://etl.example.test", raising=False)
    monkeypatch.setattr(settings, "MARKER_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MARKER_API_URL", "", raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "https://paddlevl.example.test/convert", raising=False)
    monkeypatch.setattr(settings, "TEXTIN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TEXTIN_API_URL", "https://textin.example.test", raising=False)
    monkeypatch.setattr(settings, "TEXTIN_APP_ID", "app-id", raising=False)
    monkeypatch.setattr(settings, "TEXTIN_SECRET_CODE", "", raising=False)
    monkeypatch.setattr(settings, "OLMOCR_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "MINERU_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINERU_LOCAL_SERVER_URL", "http://mineru.local", raising=False)
    monkeypatch.setattr(settings, "MINERU_API_TOKEN", "", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_API_URL", "", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_CLI", "magic-pdf", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_MODELS_DIR", "/models", raising=False)

    status = asyncio.run(
        settings_api.get_system_status(
            tenant_id=uuid4(),
            account_id="reader",
            db=SimpleNamespace(),
        )
    )

    assert status["database"] == {"connected": True, "message": "connected"}
    assert status["milvus"] == {"connected": True, "message": "connected"}
    assert status["llm"] == {"configured": True, "model": "gpt-5.4-mini"}
    assert status["embedding"] == {"configured": True, "model": "text-embedding-3-small"}
    assert status["parsers"]["qianfan_ocr"] == {
        "enabled": True,
        "available": False,
        "message": "configured (health_not_ok: upstream-down)",
        "health": {"ok": False, "reason": "upstream-down"},
    }
    assert status["parsers"]["paddle_vl"] == {
        "enabled": True,
        "available": True,
        "message": "configured (v2, doc_parser)",
        "health": {"ok": True, "pipeline_version": "v2", "mode": "doc_parser"},
    }
    assert status["parsers"]["textin"] == {
        "enabled": True,
        "available": False,
        "message": "missing secret_code",
    }
    assert status["parsers"]["mineru"] == {
        "enabled": True,
        "available": True,
        "message": "configured (local)",
    }
    assert status["parsers"]["magicpdf"] == {
        "enabled": True,
        "available": True,
        "message": "configured (models: /models/magicpdf)",
    }
