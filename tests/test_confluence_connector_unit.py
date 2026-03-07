from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


def _import_connectors_with_lightweight_stubs():  # noqa: ANN202
    module_name = "test_support_connectors_module"
    sys.modules.pop(module_name, None)

    connector_schemas = types.ModuleType("app.api.schemas.connector")
    for name in [
        "ConfluenceSpaceConnectorConfig",
        "ConnectorConfigCreateRequest",
        "ConnectorConfigListResponse",
        "ConnectorConfigOut",
        "ConnectorConfigUpdateRequest",
        "ConnectorInfo",
        "ConnectorRunCreateRequest",
        "ConnectorRunListResponse",
        "ConnectorRunOut",
        "ConnectorValidateRequest",
        "ConnectorValidateResponse",
        "DriveFilesConnectorConfig",
        "GitHubRepoConnectorConfig",
        "MinioBucketConnectorConfig",
        "MySQLCatalogConnectorConfig",
        "SQLServerCatalogConnectorConfig",
        "UrlBatchConnectorConfig",
        "WebCrawlConnectorConfig",
    ]:
        setattr(connector_schemas, name, type(name, (BaseModel,), {}))
    sys.modules["app.api.schemas.connector"] = connector_schemas

    documents = types.ModuleType("app.api.v1.documents")

    class _DummyRequest:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return None

    async def _noop_async(*_args, **_kwargs):  # noqa: ANN002, ANN003
        return None

    documents.LocalHtmlIngestRequest = _DummyRequest
    documents.UrlUploadRequest = _DummyRequest
    documents._ingest_local_html_request = _noop_async
    documents._ingest_url_upload_request = _noop_async
    documents._normalize_datetime_utc_iso = lambda *_a, **_k: None
    documents._resolve_writable_dataset = lambda *_a, **_k: None
    sys.modules["app.api.v1.documents"] = documents

    web_crawler = types.ModuleType("app.services.web_crawler")
    web_crawler.crawl_site = _noop_async
    sys.modules["app.services.web_crawler"] = web_crawler

    queue_mod = types.ModuleType("app.tasks.queue")
    queue_mod.enqueue_connector_run = lambda *_a, **_k: None
    queue_mod.get_queue = lambda *_a, **_k: None
    sys.modules["app.tasks.queue"] = queue_mod

    module_path = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "connectors.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_confluence_join_webui_preserves_context_path():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    base = "https://example.atlassian.net/wiki"
    webui = "/spaces/DOCS/pages/12345/Hello"
    out = connectors._confluence_join_webui(base=base, webui=webui)
    assert out == "https://example.atlassian.net/wiki/spaces/DOCS/pages/12345/Hello"


def test_confluence_api_base_url_normalizes_rest_api_suffix():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._confluence_api_base_url("https://c.example.com/wiki") == "https://c.example.com/wiki/rest/api"
    assert connectors._confluence_api_base_url("https://c.example.com/wiki/") == "https://c.example.com/wiki/rest/api"
    assert connectors._confluence_api_base_url("https://c.example.com/rest/api") == "https://c.example.com/rest/api"


def test_confluence_ingest_method_defaults_to_api_view():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._confluence_ingest_method({}) == "api_view"
    assert connectors._confluence_ingest_method({"ingest_method": "api_view"}) == "api_view"
    assert connectors._confluence_ingest_method({"ingest_method": "webui"}) == "webui"
    assert connectors._confluence_ingest_method({"ingest_method": "WEBUI"}) == "webui"
    assert connectors._confluence_ingest_method({"ingest_method": "nope"}) == "api_view"


def test_confluence_attachment_limits_defaults_and_clamps():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    include, per_page, total = connectors._confluence_attachment_limits({})
    assert include is False
    assert per_page == 10
    assert total == 200

    include, per_page, total = connectors._confluence_attachment_limits(
        {
            "include_attachments": True,
            "max_attachments_per_page": 999,
            "max_total_attachments": 9999,
        }
    )
    assert include is True
    assert per_page == 50
    assert total == 2000

    include, per_page, total = connectors._confluence_attachment_limits(
        {
            "include_attachments": True,
            "max_attachments_per_page": 0,
            "max_total_attachments": 0,
        }
    )
    assert include is True
    assert per_page == 10
    assert total == 200


def test_confluence_attachment_download_url_joins_base_and_download_path():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    base = "https://example.atlassian.net/wiki"
    download = "/download/attachments/12345/file.pdf"
    out = connectors._confluence_attachment_download_url(base=base, download=download)
    assert out == "https://example.atlassian.net/wiki/download/attachments/12345/file.pdf"


def test_confluence_extract_attachments_builds_download_urls_and_bounds():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    data = {
        "_links": {"base": "https://example.atlassian.net/wiki"},
        "results": [
            {
                "id": "att-1",
                "title": "file.pdf",
                "_links": {"download": "/download/attachments/12345/file.pdf"},
            },
            {
                # Missing id -> skip
                "id": "",
                "title": "skip.pdf",
                "_links": {"download": "/download/attachments/12345/skip.pdf"},
            },
            {
                "id": "att-2",
                "title": "two.docx",
                "_links": {"download": "/download/attachments/12345/two.docx"},
            },
        ],
    }

    out = connectors._confluence_extract_attachments(data, link_base_fallback="https://fallback.invalid", limit=1)
    assert out == [
        {
            "attachment_id": "att-1",
            "filename": "file.pdf",
            "download_url": "https://example.atlassian.net/wiki/download/attachments/12345/file.pdf",
        }
    ]


def test_confluence_attachment_connector_metadata_contains_required_fields():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    out = connectors._confluence_attachment_connector_metadata(
        base_url="https://example.atlassian.net/wiki",
        space_key="DOCS",
        page_id="12345",
        page_title="Hello",
        page_url="https://example.atlassian.net/wiki/spaces/DOCS/pages/12345/Hello",
        attachment_id="att-1",
        filename="file.pdf",
        download_url="https://example.atlassian.net/wiki/download/attachments/12345/file.pdf",
        run_id="run-123",
        mode="full",
        ingest_method="api_view",
    )

    assert out.get("connector_id") == "confluence_space"
    assert out.get("page_id") == "12345"
    assert out.get("attachment_id") == "att-1"
    assert out.get("filename") == "file.pdf"
    assert out.get("download_url") == "https://example.atlassian.net/wiki/download/attachments/12345/file.pdf"


def test_sync_connector_config_from_run_persists_last_modified():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    cfg_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    class _Cfg:
        def __init__(self):  # noqa: ANN001
            self.id = cfg_id
            self.tenant_id = tenant_id
            self.state = {}
            self.last_error = "prev"
            self.last_run_at = None

    cfg = _Cfg()

    class _DummyQuery:
        def __init__(self, obj):  # noqa: ANN001
            self._obj = obj

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN201
            return self._obj

    class _DummyDB:
        def query(self, _model):  # noqa: ANN001
            return _DummyQuery(cfg)

        def commit(self) -> None:
            return None

    run = type(
        "_Run",
        (),
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "connector_id": "confluence_space",
            "status": "completed",
            "error_message": None,
            "started_at": datetime.now(timezone.utc),
            "finished_at": None,
            "stats": {"config_id": str(cfg_id), "last_modified": "2026-02-14T00:00:00.000Z"},
        },
    )()

    connectors._sync_connector_config_from_run(_DummyDB(), run=run)
    assert cfg.state.get("last_modified") == "2026-02-14T00:00:00.000Z"
    assert cfg.state.get("last_run_id") == str(run.id)


def test_sync_connector_config_from_run_persists_cursor_for_github_repo():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    cfg_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    class _Cfg:
        def __init__(self):  # noqa: ANN001
            self.id = cfg_id
            self.tenant_id = tenant_id
            self.state = {"keep": "me"}
            self.last_error = "prev"
            self.last_run_at = None

    cfg = _Cfg()

    class _DummyQuery:
        def __init__(self, obj):  # noqa: ANN001
            self._obj = obj

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN201
            return self._obj

    class _DummyDB:
        def query(self, _model):  # noqa: ANN001
            return _DummyQuery(cfg)

        def commit(self) -> None:
            return None

    run = type(
        "_Run",
        (),
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "connector_id": "github_repo",
            "status": "completed",
            "error_message": None,
            "started_at": datetime.now(timezone.utc),
            "finished_at": None,
            "stats": {"config_id": str(cfg_id), "cursor": 12},
        },
    )()

    connectors._sync_connector_config_from_run(_DummyDB(), run=run)
    assert cfg.state.get("keep") == "me"
    assert cfg.state.get("cursor") == 12
    assert cfg.state.get("last_run_id") == str(run.id)
