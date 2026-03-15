from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from tests.helpers.async_utils import yield_control


def _import_connectors_with_lightweight_stubs():  # noqa: ANN202
    module_name = "test_support_connectors_module"
    sentinel = object()
    replaced: dict[str, object] = {}

    def _swap(name: str, module: types.ModuleType) -> None:
        replaced[name] = sys.modules.get(name, sentinel)
        sys.modules[name] = module

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
            return None

    async def _noop_async(*_args, **_kwargs):  # noqa: ANN002, ANN003
        await yield_control()
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


def test_jira_api_base_url_normalizes_rest_api_suffix():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    assert connectors._jira_api_base_url("https://example.atlassian.net") == "https://example.atlassian.net/rest/api/3"
    assert connectors._jira_api_base_url("https://example.atlassian.net/") == "https://example.atlassian.net/rest/api/3"
    assert connectors._jira_api_base_url("https://example.atlassian.net/rest/api/3") == "https://example.atlassian.net/rest/api/3"


def test_jira_extract_issue_updated_prefers_fields_updated():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    issue = {
        "updated": "2026-03-01T00:00:00.000+0000",
        "fields": {
            "updated": "2026-03-02T12:34:56.000+0000",
        },
    }

    assert connectors._jira_extract_issue_updated(issue) == "2026-03-02T12:34:56.000+0000"


def test_jira_attachment_limits_defaults_and_clamps():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    include, per_issue, total = connectors._jira_attachment_limits({})
    assert include is False
    assert per_issue == 10
    assert total == 200

    include, per_issue, total = connectors._jira_attachment_limits(
        {
            "include_attachments": True,
            "max_attachments_per_issue": 999,
            "max_total_attachments": 9999,
        }
    )
    assert include is True
    assert per_issue == 50
    assert total == 2000


def test_jira_extract_attachments_builds_refs_and_bounds():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    issue = {
        "fields": {
            "attachment": [
                {
                    "id": "2001",
                    "filename": "design.pdf",
                    "content": "https://example.atlassian.net/secure/attachment/2001/design.pdf",
                },
                {
                    "id": "",
                    "filename": "skip.pdf",
                    "content": "https://example.atlassian.net/secure/attachment/2002/skip.pdf",
                },
                {
                    "id": "2003",
                    "filename": "notes.txt",
                    "content": "https://example.atlassian.net/secure/attachment/2003/notes.txt",
                },
            ]
        }
    }

    out = connectors._jira_extract_attachments(issue, limit=1)
    assert out == [
        {
            "attachment_id": "2001",
            "filename": "design.pdf",
            "download_url": "https://example.atlassian.net/secure/attachment/2001/design.pdf",
        }
    ]


def test_jira_attachment_connector_metadata_contains_required_fields():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    out = connectors._jira_attachment_connector_metadata(
        base_url="https://example.atlassian.net",
        project_key="PLAT",
        issue_id="10000",
        issue_key="PLAT-42",
        issue_url="https://example.atlassian.net/browse/PLAT-42",
        attachment_id="2001",
        filename="design.pdf",
        download_url="https://example.atlassian.net/secure/attachment/2001/design.pdf",
        run_id="run-123",
        mode="incremental",
    )

    assert out.get("connector_id") == "jira_project"
    assert out.get("doc_kind") == "attachment"
    assert out.get("issue_key") == "PLAT-42"
    assert out.get("attachment_id") == "2001"
    assert out.get("download_url") == "https://example.atlassian.net/secure/attachment/2001/design.pdf"


def test_jira_issue_acl_principal_keys_collects_security_and_comment_visibility():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    issue = {
        "fields": {
            "security": {"id": "10001", "name": "Executives"},
            "comment": {
                "comments": [
                    {"visibility": {"type": "group", "value": "jira-software-users"}},
                    {"visibility": {"type": "role", "value": "Developers"}},
                    {"visibility": {"type": "group", "value": "jira-software-users"}},
                ]
            },
        }
    }

    restricted, keys = connectors._jira_issue_acl_principal_keys(issue, include_comments=True, max_comments=20)
    assert restricted is True
    assert keys == [
        "jira:group:jira-software-users",
        "jira:policy:security-level/10001",
        "jira:role:developers",
    ]


def test_jira_issue_acl_principal_keys_respects_zero_comment_limit():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    issue = {
        "fields": {
            "security": {"id": "10001"},
            "comment": {
                "comments": [
                    {"visibility": {"type": "role", "value": "Developers"}},
                ]
            },
        }
    }

    restricted, keys = connectors._jira_issue_acl_principal_keys(issue, include_comments=True, max_comments=0)
    assert restricted is True
    assert keys == ["jira:policy:security-level/10001"]


def test_jira_render_issue_html_contains_ticket_sections():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    issue = {
        "id": "10000",
        "key": "PLAT-42",
        "fields": {
            "summary": "Sync ACL drift to search index",
            "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Description body"}]}]},
            "updated": "2026-03-02T12:34:56.000+0000",
            "issuetype": {"name": "Bug"},
            "priority": {"name": "High"},
            "status": {"name": "In Progress"},
            "labels": ["acl", "search"],
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Ada"},
                        "created": "2026-03-02T13:00:00.000+0000",
                        "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Comment body"}]}]},
                    }
                ]
            },
        },
        "renderedFields": {
            "description": "<p>Description body</p>",
            "comment": {"comments": [{"body": "<p>Comment body</p>"}]},
        },
    }

    html = connectors._jira_render_issue_html(
        base_url="https://example.atlassian.net",
        issue=issue,
        include_comments=True,
        max_comments=20,
    )

    assert "PLAT-42" in html
    assert "Summary" in html
    assert "Description" in html
    assert "Comments" in html
    assert "Sync ACL drift to search index" in html
    assert "Description body" in html
    assert "Comment body" in html


def test_jira_render_issue_html_falls_back_to_rich_adf_rendering():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    issue = {
        "id": "10000",
        "key": "PLAT-99",
        "fields": {
            "summary": "ADF rendering smoke test",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "See "},
                            {
                                "type": "text",
                                "text": "docs",
                                "marks": [{"type": "link", "attrs": {"href": "https://example.com/docs"}}],
                            },
                            {"type": "text", "text": " for details."},
                        ],
                    },
                    {
                        "type": "bulletList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [
                                    {"type": "paragraph", "content": [{"type": "text", "text": "First item"}]}
                                ],
                            },
                            {
                                "type": "listItem",
                                "content": [
                                    {"type": "paragraph", "content": [{"type": "text", "text": "Second item"}]}
                                ],
                            },
                        ],
                    },
                ],
            },
            "updated": "2026-03-02T12:34:56.000+0000",
            "issuetype": {"name": "Task"},
            "priority": {"name": "Medium"},
            "status": {"name": "Open"},
            "labels": [],
            "comment": {"comments": []},
        },
        # Intentionally omit renderedFields so description must use the ADF fallback.
    }

    html = connectors._jira_render_issue_html(
        base_url="https://example.atlassian.net",
        issue=issue,
        include_comments=False,
        max_comments=0,
    )

    assert 'href="https://example.com/docs"' in html
    assert "<ul>" in html
    assert "First item" in html
    assert "Second item" in html


def test_jira_render_issue_html_includes_selected_custom_fields():  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()

    issue = {
        "id": "10000",
        "key": "PLAT-123",
        "fields": {
            "summary": "Render custom fields",
            "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Body"}]}]},
            "updated": "2026-03-02T12:34:56.000+0000",
            "issuetype": {"name": "Task"},
            "priority": {"name": "Medium"},
            "status": {"name": "Open"},
            "labels": [],
            "comment": {"comments": []},
            # Custom fields are only present when explicitly fetched via the Jira fields=... allowlist.
            "customfield_10016": {"value": "Customer impact: high"},
            "customfield_10017": ["alpha", "beta"],
        },
        "renderedFields": {},
    }

    html = connectors._jira_render_issue_html(
        base_url="https://example.atlassian.net",
        issue=issue,
        include_comments=False,
        max_comments=0,
    )

    assert "Custom Fields" in html
    assert "customfield_10016" in html
    assert "Customer impact: high" in html
    assert "customfield_10017" in html
    assert "alpha" in html
    assert "beta" in html


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
            "started_at": datetime.now(UTC),
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
            "started_at": datetime.now(UTC),
            "finished_at": None,
            "stats": {"config_id": str(cfg_id), "cursor": 12},
        },
    )()

    connectors._sync_connector_config_from_run(_DummyDB(), run=run)
    assert cfg.state.get("keep") == "me"
    assert cfg.state.get("cursor") == 12
    assert cfg.state.get("last_run_id") == str(run.id)


def test_sync_connector_config_from_run_versions_state_and_emits_audit(monkeypatch):  # noqa: ANN001
    connectors = _import_connectors_with_lightweight_stubs()
    import app.services.audit_log_service as audit_log_service

    cfg_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    seen: dict[str, object] = {}

    class _Cfg:
        def __init__(self):  # noqa: ANN001
            self.id = cfg_id
            self.tenant_id = tenant_id
            self.state = {
                "source_manifest": {"a.md": "sha-a"},
                "state_schema_version": 1,
                "state_revision": 1,
                "state_audit": {"history": [{"revision": 1, "run_id": "prev", "updated_keys": ["cursor"]}]},
            }
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

    def _capture_audit(_db, **kwargs):  # noqa: ANN001
        seen.update(kwargs)

    monkeypatch.setattr(audit_log_service, "audit_log_event", _capture_audit, raising=True)

    finished_at = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    run = type(
        "_Run",
        (),
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "connector_id": "github_repo",
            "status": "completed",
            "error_message": None,
            "started_at": finished_at,
            "finished_at": finished_at,
            "stats": {
                "config_id": str(cfg_id),
                "cursor": 12,
                "total_files": 12,
                "source_manifest": {"a.md": "sha-a", "b.md": "sha-b"},
            },
        },
    )()

    connectors._sync_connector_config_from_run(_DummyDB(), run=run)

    assert cfg.state.get("state_schema_version") == 2
    assert cfg.state.get("state_revision") == 2
    assert cfg.state.get("state_recorded_at") == "2026-03-07T12:00:00Z"
    assert cfg.state.get("source_manifest") == {"a.md": "sha-a", "b.md": "sha-b"}
    assert (cfg.state.get("state_audit") or {}).get("last_status") == "completed"

    assert seen.get("action") == "connector_config.state.sync"
    assert seen.get("resource_type") == "connector_config"
    assert seen.get("resource_id") == str(cfg_id)
    details = dict(seen.get("details") or {})
    assert details.get("connector_id") == "github_repo"
    assert details.get("config_id") == str(cfg_id)
    assert details.get("run_id") == str(run.id)
    assert details.get("revision") == 2
    assert details.get("updated_keys") == ["cursor", "last_run_id", "source_manifest", "total_files"]
