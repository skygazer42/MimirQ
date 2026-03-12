from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import BaseModel


def _import_connectors_with_lightweight_stubs():  # noqa: ANN202
    module_name = f"test_saved_state_connectors_{uuid.uuid4().hex}"
    sentinel = object()
    replaced: dict[str, object] = {}

    def _swap(name: str, module: types.ModuleType) -> None:
        replaced[name] = sys.modules.get(name, sentinel)
        sys.modules[name] = module

    auth_deps = types.ModuleType("app.api.dependencies.auth")
    auth_deps.get_current_account_id = lambda: "tester"
    _swap("app.api.dependencies.auth", auth_deps)

    tenant_deps = types.ModuleType("app.api.dependencies.tenant")
    tenant_deps.get_tenant_id = lambda: uuid.uuid4()
    _swap("app.api.dependencies.tenant", tenant_deps)

    deps_pkg = types.ModuleType("app.api.dependencies")
    deps_pkg.get_current_account_id = auth_deps.get_current_account_id
    deps_pkg.get_tenant_id = tenant_deps.get_tenant_id
    deps_pkg.auth = auth_deps
    deps_pkg.tenant = tenant_deps
    _swap("app.api.dependencies", deps_pkg)

    config_mod = types.ModuleType("app.core.config")
    config_mod.settings = types.SimpleNamespace(
        DATABASE_URL="sqlite:///./tests_saved_state_stub.db",
        SECRET_KEY="tests-secret-key",
        SECRET_KEY_FALLBACKS="",
        URL_INGEST_ENABLED=True,
        URL_INGEST_TIMEOUT_SEC=30.0,
        URL_INGEST_MAX_BYTES=0,
        URL_INGEST_FOLLOW_REDIRECTS=False,
        MAX_FILE_SIZE=10_000_000,
        TASK_QUEUE_ENABLED=False,
        MINIO_ENABLED=False,
        DB_CATALOG_ENABLED=False,
    )
    _swap("app.core.config", config_mod)

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
        "JiraProjectConnectorConfig",
        "MinioBucketConnectorConfig",
        "MySQLCatalogConnectorConfig",
        "SQLServerCatalogConnectorConfig",
        "UrlBatchConnectorConfig",
        "WebCrawlConnectorConfig",
    ]:
        setattr(connector_schemas, name, type(name, (BaseModel,), {}))
    _swap("app.api.schemas.connector", connector_schemas)

    documents = types.ModuleType("app.api.v1.documents")

    class _DummyRequest:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            for idx, arg in enumerate(args):
                setattr(self, f"arg_{idx}", arg)
            for key, value in kwargs.items():
                setattr(self, key, value)

    async def _noop_async(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return None

    documents.LocalHtmlIngestRequest = _DummyRequest
    documents.UrlUploadRequest = _DummyRequest
    documents._ingest_local_html_request = _noop_async
    documents._ingest_url_upload_request = _noop_async
    documents._normalize_datetime_utc_iso = lambda *_a, **_k: None
    documents._resolve_writable_dataset = lambda *_a, **_k: None
    _swap("app.api.v1.documents", documents)

    web_crawler = types.ModuleType("app.services.web_crawler")
    web_crawler.crawl_site = _noop_async
    _swap("app.services.web_crawler", web_crawler)

    queue_mod = types.ModuleType("app.tasks.queue")
    queue_mod.enqueue_connector_run = lambda *_a, **_k: None
    queue_mod.get_queue = lambda *_a, **_k: None
    _swap("app.tasks.queue", queue_mod)

    module_path = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "connectors.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)
        for name, previous in replaced.items():
            if previous is sentinel:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


class _DummyQuery:
    def __init__(self, run):  # noqa: ANN001
        self._run = run

    def options(self, *_a, **_k):  # noqa: ANN001
        return self

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        return self._run


class _DummyDB:
    def __init__(self, run):  # noqa: ANN001
        self._run = run
        self.commits = 0

    def query(self, *_a, **_k):  # noqa: ANN001
        return _DummyQuery(self._run)

    def add(self, obj) -> None:  # noqa: ANN001
        self._run.documents.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class _DummyDoc:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.access_mode = None
        self.owner_id = ""


def _make_run(*, connector_id: str, config: dict, stats: dict | None = None):  # noqa: ANN202
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Run:
        def __init__(self) -> None:
            self.id = run_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.connector_id = connector_id
            self.requested_by = "tester"
            self.status = "pending"
            self.config = config
            self.stats = dict(stats or {})
            self.error_message = None
            self.started_at = None
            self.finished_at = None
            self.documents = []

    return _Run(), run_id, tenant_id


@pytest.mark.asyncio
async def test_execute_web_crawl_run_resumes_from_saved_state_cursor(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="web_crawl",
        config={
            "start_urls": ["https://example.com/docs"],
            "max_pages": 4,
            "_state": {"cursor": 2},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    crawl = types.SimpleNamespace(
        urls=[
            "https://example.com/docs/a",
            "https://example.com/docs/b",
            "https://example.com/docs/c",
            "https://example.com/docs/d",
        ],
        visited=4,
        queued=4,
        errors=[],
    )

    async def _fake_crawl_site(*_a, **_k):  # noqa: ANN202
        return crawl

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    monkeypatch.setattr(connectors, "crawl_site", _fake_crawl_site, raising=True)
    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors._execute_web_crawl_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == ["https://example.com/docs/c", "https://example.com/docs/d"]
    assert int((run.stats or {}).get("processed_urls") or 0) == 4
    assert int((run.stats or {}).get("cursor") or 0) == 4
    assert bool((run.stats or {}).get("resumed_from_state")) is True


@pytest.mark.asyncio
async def test_execute_web_crawl_run_incremental_skips_unchanged_urls(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="web_crawl",
        config={
            "start_urls": ["https://example.com/docs"],
            "max_pages": 4,
            "_state": {
                "source_manifest": {
                    "https://example.com/docs/a": "sha-a",
                    "https://example.com/docs/b": "sha-b",
                }
            },
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    crawl = types.SimpleNamespace(
        urls=[
            "https://example.com/docs/a",
            "https://example.com/docs/b",
            "https://example.com/docs/c",
        ],
        visited=3,
        queued=3,
        errors=[],
    )

    async def _fake_crawl_site(*_a, **_k):  # noqa: ANN202
        return crawl

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    monkeypatch.setattr(connectors, "crawl_site", _fake_crawl_site, raising=True)
    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors._execute_web_crawl_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == ["https://example.com/docs/c"]
    assert (run.stats or {}).get("mode") == "incremental"
    assert int((run.stats or {}).get("delta_urls") or 0) == 1
    assert int((run.stats or {}).get("skipped_unchanged") or 0) == 2
    assert int((run.stats or {}).get("processed_urls") or 0) == 3
    assert set(((run.stats or {}).get("source_manifest") or {}).keys()) == {
        "https://example.com/docs/a",
        "https://example.com/docs/b",
        "https://example.com/docs/c",
    }


@pytest.mark.asyncio
async def test_execute_web_crawl_run_incremental_prunes_removed_urls_and_soft_disables_documents(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="web_crawl",
        config={
            "start_urls": ["https://example.com/docs"],
            "max_pages": 4,
            "_state": {
                "source_manifest": {
                    "https://example.com/docs/a": "sha-a",
                    "https://example.com/docs/obsolete": "sha-obsolete",
                }
            },
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    crawl = types.SimpleNamespace(
        urls=[
            "https://example.com/docs/a",
            "https://example.com/docs/b",
        ],
        visited=2,
        queued=2,
        errors=[],
    )

    async def _fake_crawl_site(*_a, **_k):  # noqa: ANN202
        return crawl

    ingested_urls: list[str] = []
    disabled_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    def _fake_soft_disable(_db, *, source_url: str, **_k):  # noqa: ANN001
        disabled_urls.append(source_url)
        return 1

    monkeypatch.setattr(connectors, "crawl_site", _fake_crawl_site, raising=True)
    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)
    monkeypatch.setattr(
        connectors,
        "_soft_disable_connector_documents_by_source_url",
        _fake_soft_disable,
        raising=True,
    )

    await connectors._execute_web_crawl_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == ["https://example.com/docs/b"]
    assert disabled_urls == ["https://example.com/docs/obsolete"]
    assert (run.stats or {}).get("mode") == "incremental"
    assert int((run.stats or {}).get("removed_paths") or 0) == 1
    assert int((run.stats or {}).get("removed_paths_reconciled") or 0) == 1
    assert int((run.stats or {}).get("removed_documents_disabled") or 0) == 1
    assert set(((run.stats or {}).get("source_manifest") or {}).keys()) == {
        "https://example.com/docs/a",
        "https://example.com/docs/b",
    }


@pytest.mark.asyncio
async def test_execute_github_repo_run_resumes_from_saved_state_cursor(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="github_repo",
        config={
            "repo": "acme/docs",
            "branch": "main",
            "max_files": 4,
            "include_extensions": [".md"],
            "_state": {"cursor": 1},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _FakeGitHubResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "tree": [
                    {"type": "blob", "path": "a.md"},
                    {"type": "blob", "path": "b.md"},
                    {"type": "blob", "path": "c.md"},
                ]
            }

    class _FakeGitHubClient:
        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

        async def get(self, *_a, **_k):  # noqa: ANN202
            return _FakeGitHubResponse()

    monkeypatch.setattr(connectors.httpx, "AsyncClient", lambda *args, **kwargs: _FakeGitHubClient(), raising=True)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors._execute_github_repo_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == [
        "https://raw.githubusercontent.com/acme/docs/main/b.md",
        "https://raw.githubusercontent.com/acme/docs/main/c.md",
    ]
    assert int((run.stats or {}).get("processed_files") or 0) == 3
    assert int((run.stats or {}).get("cursor") or 0) == 3
    assert bool((run.stats or {}).get("resumed_from_state")) is True


@pytest.mark.asyncio
async def test_execute_github_repo_run_incremental_skips_unchanged_blob_shas(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="github_repo",
        config={
            "repo": "acme/docs",
            "branch": "main",
            "max_files": 4,
            "include_extensions": [".md"],
            "_state": {"source_manifest": {"a.md": "sha-a", "b.md": "sha-b-old"}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _FakeGitHubResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "tree": [
                    {"type": "blob", "path": "a.md", "sha": "sha-a"},
                    {"type": "blob", "path": "b.md", "sha": "sha-b-new"},
                    {"type": "blob", "path": "c.md", "sha": "sha-c"},
                ]
            }

    class _FakeGitHubClient:
        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

        async def get(self, *_a, **_k):  # noqa: ANN202
            return _FakeGitHubResponse()

    monkeypatch.setattr(connectors.httpx, "AsyncClient", lambda *args, **kwargs: _FakeGitHubClient(), raising=True)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors._execute_github_repo_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == [
        "https://raw.githubusercontent.com/acme/docs/main/b.md",
        "https://raw.githubusercontent.com/acme/docs/main/c.md",
    ]
    assert (run.stats or {}).get("mode") == "incremental"
    assert int((run.stats or {}).get("delta_files") or 0) == 2
    assert int((run.stats or {}).get("skipped_unchanged") or 0) == 1
    assert int((run.stats or {}).get("processed_files") or 0) == 3
    assert (run.stats or {}).get("source_manifest") == {"a.md": "sha-a", "b.md": "sha-b-new", "c.md": "sha-c"}


@pytest.mark.asyncio
async def test_execute_github_repo_run_incremental_noop_when_manifest_matches(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="github_repo",
        config={
            "repo": "acme/docs",
            "branch": "main",
            "max_files": 4,
            "include_extensions": [".md"],
            "_state": {"source_manifest": {"a.md": "sha-a", "b.md": "sha-b"}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _FakeGitHubResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "tree": [
                    {"type": "blob", "path": "a.md", "sha": "sha-a"},
                    {"type": "blob", "path": "b.md", "sha": "sha-b"},
                ]
            }

    class _FakeGitHubClient:
        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

        async def get(self, *_a, **_k):  # noqa: ANN202
            return _FakeGitHubResponse()

    monkeypatch.setattr(connectors.httpx, "AsyncClient", lambda *args, **kwargs: _FakeGitHubClient(), raising=True)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors._execute_github_repo_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == []
    assert (run.stats or {}).get("mode") == "incremental"
    assert int((run.stats or {}).get("delta_files") or 0) == 0
    assert int((run.stats or {}).get("skipped_unchanged") or 0) == 2
    assert int((run.stats or {}).get("created") or 0) == 0
    assert (run.stats or {}).get("source_manifest") == {"a.md": "sha-a", "b.md": "sha-b"}


@pytest.mark.asyncio
async def test_execute_github_repo_run_incremental_partial_failure_only_advances_successful_manifest(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="github_repo",
        config={
            "repo": "acme/docs",
            "branch": "main",
            "max_files": 4,
            "include_extensions": [".md"],
            "_state": {"source_manifest": {"a.md": "sha-a-old"}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _FakeGitHubResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "tree": [
                    {"type": "blob", "path": "a.md", "sha": "sha-a-new"},
                    {"type": "blob", "path": "b.md", "sha": "sha-b"},
                ]
            }

    class _FakeGitHubClient:
        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

        async def get(self, *_a, **_k):  # noqa: ANN202
            return _FakeGitHubResponse()

    monkeypatch.setattr(connectors.httpx, "AsyncClient", lambda *args, **kwargs: _FakeGitHubClient(), raising=True)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        url = str(getattr(body, "url", ""))
        ingested_urls.append(url)
        if url.endswith("/a.md"):
            raise RuntimeError("boom")
        return _DummyDoc()

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors._execute_github_repo_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == [
        "https://raw.githubusercontent.com/acme/docs/main/a.md",
        "https://raw.githubusercontent.com/acme/docs/main/b.md",
    ]
    assert int((run.stats or {}).get("created") or 0) == 1
    assert int((run.stats or {}).get("failed") or 0) == 1
    assert (run.stats or {}).get("source_manifest") == {"a.md": "sha-a-old", "b.md": "sha-b"}


@pytest.mark.asyncio
async def test_execute_github_repo_run_incremental_prunes_removed_paths_and_soft_disables_documents(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="github_repo",
        config={
            "repo": "acme/docs",
            "branch": "main",
            "max_files": 4,
            "include_extensions": [".md"],
            "_state": {"source_manifest": {"a.md": "sha-a", "obsolete.md": "sha-obsolete"}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _FakeGitHubResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "tree": [
                    {"type": "blob", "path": "a.md", "sha": "sha-a"},
                    {"type": "blob", "path": "b.md", "sha": "sha-b"},
                ]
            }

    class _FakeGitHubClient:
        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

        async def get(self, *_a, **_k):  # noqa: ANN202
            return _FakeGitHubResponse()

    monkeypatch.setattr(connectors.httpx, "AsyncClient", lambda *args, **kwargs: _FakeGitHubClient(), raising=True)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    removed_sources: list[str] = []

    def _fake_soft_disable(_db, *, source_url: str, **_k):  # noqa: ANN001
        removed_sources.append(source_url)
        return 2

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)
    monkeypatch.setattr(
        connectors,
        "_soft_disable_connector_documents_by_source_url",
        _fake_soft_disable,
        raising=False,
    )

    await connectors._execute_github_repo_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == ["https://raw.githubusercontent.com/acme/docs/main/b.md"]
    assert removed_sources == ["https://raw.githubusercontent.com/acme/docs/main/obsolete.md"]
    assert int((run.stats or {}).get("removed_paths") or 0) == 1
    assert int((run.stats or {}).get("removed_documents_disabled") or 0) == 2
    assert int((run.stats or {}).get("removed_paths_reconciled") or 0) == 1
    assert (run.stats or {}).get("source_manifest") == {"a.md": "sha-a", "b.md": "sha-b"}


@pytest.mark.asyncio
async def test_execute_github_repo_run_does_not_mark_tracked_paths_removed_when_now_filtered_by_extension(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="github_repo",
        config={
            "repo": "acme/docs",
            "branch": "main",
            "max_files": 4,
            "include_extensions": [".md"],
            "_state": {"source_manifest": {"legacy.txt": "sha-legacy"}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _FakeGitHubResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "tree": [
                    {"type": "blob", "path": "legacy.txt", "sha": "sha-legacy"},
                    {"type": "blob", "path": "fresh.md", "sha": "sha-fresh"},
                ]
            }

    class _FakeGitHubClient:
        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

        async def get(self, *_a, **_k):  # noqa: ANN202
            return _FakeGitHubResponse()

    monkeypatch.setattr(connectors.httpx, "AsyncClient", lambda *args, **kwargs: _FakeGitHubClient(), raising=True)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    removed_sources: list[str] = []

    def _fake_soft_disable(_db, *, source_url: str, **_k):  # noqa: ANN001
        removed_sources.append(source_url)
        return 1

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)
    monkeypatch.setattr(
        connectors,
        "_soft_disable_connector_documents_by_source_url",
        _fake_soft_disable,
        raising=False,
    )

    await connectors._execute_github_repo_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == ["https://raw.githubusercontent.com/acme/docs/main/fresh.md"]
    assert removed_sources == []
    assert int((run.stats or {}).get("removed_paths") or 0) == 0
    assert (run.stats or {}).get("source_manifest") == {"fresh.md": "sha-fresh", "legacy.txt": "sha-legacy"}


@pytest.mark.asyncio
async def test_execute_github_repo_run_does_not_mark_tracked_paths_removed_when_outside_max_files_window(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="github_repo",
        config={
            "repo": "acme/docs",
            "branch": "main",
            "max_files": 1,
            "include_extensions": [".md"],
            "_state": {"source_manifest": {"z.md": "sha-z"}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _FakeGitHubResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "tree": [
                    {"type": "blob", "path": "a.md", "sha": "sha-a"},
                    {"type": "blob", "path": "z.md", "sha": "sha-z"},
                ]
            }

    class _FakeGitHubClient:
        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

        async def get(self, *_a, **_k):  # noqa: ANN202
            return _FakeGitHubResponse()

    monkeypatch.setattr(connectors.httpx, "AsyncClient", lambda *args, **kwargs: _FakeGitHubClient(), raising=True)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    removed_sources: list[str] = []

    def _fake_soft_disable(_db, *, source_url: str, **_k):  # noqa: ANN001
        removed_sources.append(source_url)
        return 1

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)
    monkeypatch.setattr(
        connectors,
        "_soft_disable_connector_documents_by_source_url",
        _fake_soft_disable,
        raising=False,
    )

    await connectors._execute_github_repo_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == ["https://raw.githubusercontent.com/acme/docs/main/a.md"]
    assert removed_sources == []
    assert int((run.stats or {}).get("removed_paths") or 0) == 0
    assert (run.stats or {}).get("source_manifest") == {"a.md": "sha-a", "z.md": "sha-z"}


@pytest.mark.asyncio
async def test_execute_drive_files_run_resumes_from_saved_state_cursor(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="drive_files",
        config={
            "urls": ["drive://file-1", "drive://file-2", "drive://file-3"],
            "_state": {"cursor": 1},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors, "_extract_drive_file_id", lambda url: str(url).split("//", 1)[-1], raising=True)
    monkeypatch.setattr(connectors, "_drive_direct_download_url", lambda file_id: f"https://drive.local/{file_id}", raising=True)

    async def _fake_drive_sync_token(*, file_id: str, source_url: str, **_k):  # noqa: ANN202
        return f"token-{file_id}-{len(source_url)}"

    monkeypatch.setattr(connectors, "_drive_fetch_file_sync_token", _fake_drive_sync_token, raising=True)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors._execute_drive_files_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == [
        "https://drive.local/file-2",
        "https://drive.local/file-3",
    ]
    assert int((run.stats or {}).get("processed_urls") or 0) == 3
    assert int((run.stats or {}).get("cursor") or 0) == 3
    assert bool((run.stats or {}).get("resumed_from_state")) is True


@pytest.mark.asyncio
async def test_execute_drive_files_run_incremental_skips_unchanged_files(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="drive_files",
        config={
            "urls": ["drive://file-a", "drive://file-b", "drive://file-c"],
            "_state": {"source_manifest": {"file-a": "token-a", "file-b": "token-b-old"}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors, "_extract_drive_file_id", lambda url: str(url).split("//", 1)[-1], raising=True)
    monkeypatch.setattr(connectors, "_drive_direct_download_url", lambda file_id: f"https://drive.local/{file_id}", raising=True)

    tokens = {"file-a": "token-a", "file-b": "token-b-new", "file-c": "token-c"}

    async def _fake_drive_sync_token(*, file_id: str, **_k):  # noqa: ANN202
        return tokens[file_id]

    monkeypatch.setattr(connectors, "_drive_fetch_file_sync_token", _fake_drive_sync_token, raising=True)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors._execute_drive_files_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == [
        "https://drive.local/file-b",
        "https://drive.local/file-c",
    ]
    assert (run.stats or {}).get("mode") == "incremental"
    assert int((run.stats or {}).get("delta_urls") or 0) == 2
    assert int((run.stats or {}).get("skipped_unchanged") or 0) == 1
    assert int((run.stats or {}).get("processed_urls") or 0) == 3
    assert (run.stats or {}).get("source_manifest") == {
        "file-a": "token-a",
        "file-b": "token-b-new",
        "file-c": "token-c",
    }


@pytest.mark.asyncio
async def test_execute_drive_files_run_incremental_noop_when_manifest_matches(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="drive_files",
        config={
            "urls": ["drive://file-a", "drive://file-b"],
            "_state": {"source_manifest": {"file-a": "token-a", "file-b": "token-b"}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors, "_extract_drive_file_id", lambda url: str(url).split("//", 1)[-1], raising=True)
    monkeypatch.setattr(connectors, "_drive_direct_download_url", lambda file_id: f"https://drive.local/{file_id}", raising=True)

    async def _fake_drive_sync_token(*, file_id: str, **_k):  # noqa: ANN202
        return {"file-a": "token-a", "file-b": "token-b"}[file_id]

    async def _fail_if_ingest_called(*_a, **_k):  # noqa: ANN202
        raise AssertionError("ingest should not be called for noop incremental run")

    monkeypatch.setattr(connectors, "_drive_fetch_file_sync_token", _fake_drive_sync_token, raising=True)
    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fail_if_ingest_called, raising=True)

    await connectors._execute_drive_files_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert (run.stats or {}).get("mode") == "incremental"
    assert int((run.stats or {}).get("delta_urls") or 0) == 0
    assert int((run.stats or {}).get("skipped_unchanged") or 0) == 2
    assert int((run.stats or {}).get("created") or 0) == 0
    assert int((run.stats or {}).get("processed_urls") or 0) == 2
    assert (run.stats or {}).get("source_manifest") == {"file-a": "token-a", "file-b": "token-b"}


@pytest.mark.asyncio
async def test_execute_drive_files_run_incremental_partial_failure_only_advances_successful_manifest(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="drive_files",
        config={
            "urls": ["drive://file-a", "drive://file-b"],
            "_state": {"source_manifest": {"file-a": "token-a-old"}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors, "_extract_drive_file_id", lambda url: str(url).split("//", 1)[-1], raising=True)
    monkeypatch.setattr(connectors, "_drive_direct_download_url", lambda file_id: f"https://drive.local/{file_id}", raising=True)

    async def _fake_drive_sync_token(*, file_id: str, **_k):  # noqa: ANN202
        return {"file-a": "token-a-new", "file-b": "token-b"}[file_id]

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        url = str(getattr(body, "url", ""))
        ingested_urls.append(url)
        if url.endswith("/file-a"):
            raise RuntimeError("boom")
        return _DummyDoc()

    monkeypatch.setattr(connectors, "_drive_fetch_file_sync_token", _fake_drive_sync_token, raising=True)
    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors._execute_drive_files_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == [
        "https://drive.local/file-a",
        "https://drive.local/file-b",
    ]
    assert int((run.stats or {}).get("created") or 0) == 1
    assert int((run.stats or {}).get("failed") or 0) == 1
    assert (run.stats or {}).get("source_manifest") == {"file-a": "token-a-old", "file-b": "token-b"}


@pytest.mark.asyncio
async def test_execute_drive_files_run_incremental_prunes_removed_files_and_soft_disables_documents(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="drive_files",
        config={
            "urls": ["drive://file-a", "drive://file-b"],
            "_state": {"source_manifest": {"file-a": "token-a", "file-obsolete": "token-obsolete"}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(connectors, "_extract_drive_file_id", lambda url: str(url).split("//", 1)[-1], raising=True)
    monkeypatch.setattr(connectors, "_drive_direct_download_url", lambda file_id: f"https://drive.local/{file_id}", raising=True)

    async def _fake_drive_sync_token(*, file_id: str, **_k):  # noqa: ANN202
        return {"file-a": "token-a", "file-b": "token-b"}[file_id]

    ingested_urls: list[str] = []
    disabled_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    def _fake_soft_disable(_db, *, source_url: str, **_k):  # noqa: ANN001
        disabled_urls.append(source_url)
        return 1

    monkeypatch.setattr(connectors, "_drive_fetch_file_sync_token", _fake_drive_sync_token, raising=True)
    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)
    monkeypatch.setattr(
        connectors,
        "_soft_disable_connector_documents_by_source_url",
        _fake_soft_disable,
        raising=True,
    )

    await connectors._execute_drive_files_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == ["https://drive.local/file-b"]
    assert disabled_urls == ["https://drive.local/file-obsolete"]
    assert (run.stats or {}).get("mode") == "incremental"
    assert int((run.stats or {}).get("removed_paths") or 0) == 1
    assert int((run.stats or {}).get("removed_paths_reconciled") or 0) == 1
    assert int((run.stats or {}).get("removed_documents_disabled") or 0) == 1
    assert (run.stats or {}).get("source_manifest") == {"file-a": "token-a", "file-b": "token-b"}


@pytest.mark.asyncio
async def test_execute_minio_bucket_run_resumes_from_saved_state_cursor(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    run, run_id, tenant_id = _make_run(
        connector_id="minio_bucket",
        config={
            "bucket": "docs",
            "include_extensions": [".md"],
            "_state": {"cursor": 1},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _MinioClient:
        def list_objects(self, **_kwargs):  # noqa: ANN001
            for name in ["a.md", "b.md", "c.md"]:
                yield types.SimpleNamespace(object_name=name)

        def presigned_get_object(self, *, object_name, **_kwargs):  # noqa: ANN001
            return f"https://minio.local/{object_name}"

    minio_module = types.ModuleType("app.storage.object.minio")
    minio_module.minio_service = types.SimpleNamespace(_get_client=lambda: _MinioClient(), _bucket_name="docs")
    monkeypatch.setitem(sys.modules, "app.storage.object.minio", minio_module)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)

    await connectors._execute_minio_bucket_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == [
        "https://minio.local/b.md",
        "https://minio.local/c.md",
    ]
    assert int((run.stats or {}).get("processed_objects") or 0) == 3
    assert int((run.stats or {}).get("cursor") or 0) == 3
    assert bool((run.stats or {}).get("resumed_from_state")) is True


@pytest.mark.asyncio
async def test_execute_minio_bucket_run_incremental_noop_does_not_reingest(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    token_a = "etag:etag-a|last_modified:2026-03-10T00:00:00Z"
    token_b = "etag:etag-b|last_modified:2026-03-10T00:00:00Z"
    run, run_id, tenant_id = _make_run(
        connector_id="minio_bucket",
        config={
            "bucket": "docs",
            "include_extensions": [".md"],
            "_state": {"source_manifest": {"a.md": token_a, "b.md": token_b}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _MinioClient:
        def list_objects(self, **_kwargs):  # noqa: ANN001
            yield types.SimpleNamespace(object_name="a.md", etag="etag-a", last_modified=datetime(2026, 3, 10, tzinfo=timezone.utc))
            yield types.SimpleNamespace(object_name="b.md", etag="etag-b", last_modified=datetime(2026, 3, 10, tzinfo=timezone.utc))

        def presigned_get_object(self, *, object_name, **_kwargs):  # noqa: ANN001
            return f"https://minio.local/{object_name}"

    minio_module = types.ModuleType("app.storage.object.minio")
    minio_module.minio_service = types.SimpleNamespace(_get_client=lambda: _MinioClient(), _bucket_name="docs")
    monkeypatch.setitem(sys.modules, "app.storage.object.minio", minio_module)

    async def _fail_if_called(*_a, **_k):  # noqa: ANN202
        raise AssertionError("ingest should not be called for noop incremental run")

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fail_if_called, raising=True)

    await connectors._execute_minio_bucket_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert (run.stats or {}).get("mode") == "incremental"
    assert int((run.stats or {}).get("delta_objects") or 0) == 0
    assert int((run.stats or {}).get("skipped_unchanged") or 0) == 2
    assert int((run.stats or {}).get("created") or 0) == 0
    assert (run.stats or {}).get("source_manifest") == {"a.md": token_a, "b.md": token_b}


@pytest.mark.asyncio
async def test_execute_minio_bucket_run_incremental_skips_unchanged_objects(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    token_a = "etag:etag-a|last_modified:2026-03-10T00:00:00Z"
    token_b = "etag:etag-b|last_modified:2026-03-10T00:00:00Z"
    token_c = "etag:etag-c|last_modified:2026-03-10T00:00:00Z"
    run, run_id, tenant_id = _make_run(
        connector_id="minio_bucket",
        config={
            "bucket": "docs",
            "include_extensions": [".md"],
            "_state": {"source_manifest": {"a.md": token_a, "b.md": token_b}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _MinioClient:
        def list_objects(self, **_kwargs):  # noqa: ANN001
            yield types.SimpleNamespace(object_name="a.md", etag="etag-a", last_modified=datetime(2026, 3, 10, tzinfo=timezone.utc))
            yield types.SimpleNamespace(object_name="b.md", etag="etag-b", last_modified=datetime(2026, 3, 10, tzinfo=timezone.utc))
            yield types.SimpleNamespace(object_name="c.md", etag="etag-c", last_modified=datetime(2026, 3, 10, tzinfo=timezone.utc))

        def presigned_get_object(self, *, object_name, **_kwargs):  # noqa: ANN001
            return f"https://minio.local/{object_name}"

    minio_module = types.ModuleType("app.storage.object.minio")
    minio_module.minio_service = types.SimpleNamespace(_get_client=lambda: _MinioClient(), _bucket_name="docs")
    monkeypatch.setitem(sys.modules, "app.storage.object.minio", minio_module)

    ingested_urls: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    def _noop_soft_disable(_db, *, source_ref: str, **_k):  # noqa: ANN001
        assert source_ref
        return 0

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)
    monkeypatch.setattr(connectors, "_soft_disable_connector_documents_by_source_ref", _noop_soft_disable, raising=True)

    await connectors._execute_minio_bucket_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == ["https://minio.local/c.md"]
    assert (run.stats or {}).get("mode") == "incremental"
    assert int((run.stats or {}).get("delta_objects") or 0) == 1
    assert int((run.stats or {}).get("skipped_unchanged") or 0) == 2
    assert int((run.stats or {}).get("processed_objects") or 0) == 3
    assert int((run.stats or {}).get("created") or 0) == 1
    assert set(((run.stats or {}).get("source_manifest") or {}).keys()) == {"a.md", "b.md", "c.md"}
    assert (run.stats or {}).get("source_manifest") == {"a.md": token_a, "b.md": token_b, "c.md": token_c}


@pytest.mark.asyncio
async def test_execute_minio_bucket_run_incremental_prunes_removed_paths_and_soft_disables_documents(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    token_a = "etag:etag-a|last_modified:2026-03-10T00:00:00Z"
    token_b = "etag:etag-b|last_modified:2026-03-10T00:00:00Z"
    token_obsolete = "etag:etag-old|last_modified:2026-03-09T00:00:00Z"
    run, run_id, tenant_id = _make_run(
        connector_id="minio_bucket",
        config={
            "bucket": "docs",
            "include_extensions": [".md"],
            "_state": {"source_manifest": {"a.md": token_a, "obsolete.md": token_obsolete}},
        },
    )
    dummy_db = _DummyDB(run)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    class _MinioClient:
        def list_objects(self, **_kwargs):  # noqa: ANN001
            yield types.SimpleNamespace(object_name="a.md", etag="etag-a", last_modified=datetime(2026, 3, 10, tzinfo=timezone.utc))
            yield types.SimpleNamespace(object_name="b.md", etag="etag-b", last_modified=datetime(2026, 3, 10, tzinfo=timezone.utc))

        def presigned_get_object(self, *, object_name, **_kwargs):  # noqa: ANN001
            return f"https://minio.local/{object_name}"

    minio_module = types.ModuleType("app.storage.object.minio")
    minio_module.minio_service = types.SimpleNamespace(_get_client=lambda: _MinioClient(), _bucket_name="docs")
    monkeypatch.setitem(sys.modules, "app.storage.object.minio", minio_module)

    ingested_urls: list[str] = []
    disabled_refs: list[str] = []

    async def _fake_ingest_url_upload_request(*, body, **_k):  # noqa: ANN202
        ingested_urls.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    def _fake_soft_disable(_db, *, source_ref: str, **_k):  # noqa: ANN001
        disabled_refs.append(source_ref)
        return 2

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request, raising=True)
    monkeypatch.setattr(connectors, "_soft_disable_connector_documents_by_source_ref", _fake_soft_disable, raising=True)

    await connectors._execute_minio_bucket_run(run_id=run_id, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls == ["https://minio.local/b.md"]
    assert disabled_refs == ["obsolete.md"]
    assert (run.stats or {}).get("mode") == "incremental"
    assert int((run.stats or {}).get("removed_paths") or 0) == 1
    assert int((run.stats or {}).get("removed_paths_reconciled") or 0) == 1
    assert int((run.stats or {}).get("removed_documents_disabled") or 0) == 2
    assert (run.stats or {}).get("source_manifest") == {"a.md": token_a, "b.md": token_b}


@pytest.mark.asyncio
async def test_execute_minio_bucket_run_incremental_partial_failure_resumed_run_retries_failed_and_skips_success(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    token_a_old = "etag:etag-a-old|last_modified:2026-03-09T00:00:00Z"
    token_a_new = "etag:etag-a-new|last_modified:2026-03-10T00:00:00Z"
    token_b = "etag:etag-b|last_modified:2026-03-10T00:00:00Z"

    class _MinioClient:
        def list_objects(self, **_kwargs):  # noqa: ANN001
            yield types.SimpleNamespace(object_name="a.md", etag="etag-a-new", last_modified=datetime(2026, 3, 10, tzinfo=timezone.utc))
            yield types.SimpleNamespace(object_name="b.md", etag="etag-b", last_modified=datetime(2026, 3, 10, tzinfo=timezone.utc))

        def presigned_get_object(self, *, object_name, **_kwargs):  # noqa: ANN001
            return f"https://minio.local/{object_name}"

    minio_module = types.ModuleType("app.storage.object.minio")
    minio_module.minio_service = types.SimpleNamespace(_get_client=lambda: _MinioClient(), _bucket_name="docs")
    monkeypatch.setitem(sys.modules, "app.storage.object.minio", minio_module)

    run1, run_id1, tenant_id = _make_run(
        connector_id="minio_bucket",
        config={
            "bucket": "docs",
            "include_extensions": [".md"],
            "_state": {"source_manifest": {"a.md": token_a_old}},
        },
    )
    dummy_db1 = _DummyDB(run1)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db1, raising=True)
    monkeypatch.setattr(connectors, "_apply_document_access_from_config", lambda *_a, **_k: None, raising=True)

    ingested_urls_1: list[str] = []

    async def _fake_ingest_url_upload_request_1(*, body, **_k):  # noqa: ANN202
        url = str(getattr(body, "url", ""))
        ingested_urls_1.append(url)
        if url.endswith("/a.md"):
            raise RuntimeError("boom")
        return _DummyDoc()

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request_1, raising=True)

    await connectors._execute_minio_bucket_run(run_id=run_id1, tenant_id=tenant_id, requested_by="tester")

    assert ingested_urls_1 == [
        "https://minio.local/a.md",
        "https://minio.local/b.md",
    ]
    assert int((run1.stats or {}).get("created") or 0) == 1
    assert int((run1.stats or {}).get("failed") or 0) == 1
    assert (run1.stats or {}).get("source_manifest") == {"a.md": token_a_old, "b.md": token_b}

    run2, run_id2, _tenant_id2 = _make_run(
        connector_id="minio_bucket",
        config={
            "bucket": "docs",
            "include_extensions": [".md"],
            "_state": {"source_manifest": dict((run1.stats or {}).get("source_manifest") or {})},
        },
    )
    dummy_db2 = _DummyDB(run2)
    monkeypatch.setattr(connectors, "SessionLocal", lambda: dummy_db2, raising=True)

    ingested_urls_2: list[str] = []

    async def _fake_ingest_url_upload_request_2(*, body, **_k):  # noqa: ANN202
        ingested_urls_2.append(str(getattr(body, "url", "")))
        return _DummyDoc()

    def _noop_soft_disable(_db, *, source_ref: str, **_k):  # noqa: ANN001
        assert source_ref
        return 0

    monkeypatch.setattr(connectors, "_ingest_url_upload_request", _fake_ingest_url_upload_request_2, raising=True)
    monkeypatch.setattr(connectors, "_soft_disable_connector_documents_by_source_ref", _noop_soft_disable, raising=True)

    await connectors._execute_minio_bucket_run(run_id=run_id2, tenant_id=_tenant_id2, requested_by="tester")

    assert ingested_urls_2 == ["https://minio.local/a.md"]
    assert int((run2.stats or {}).get("created") or 0) == 1
    assert int((run2.stats or {}).get("failed") or 0) == 0
    assert (run2.stats or {}).get("source_manifest") == {"a.md": token_a_new, "b.md": token_b}
