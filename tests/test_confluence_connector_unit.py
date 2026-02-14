from __future__ import annotations

import uuid
from datetime import datetime, timezone


def test_confluence_join_webui_preserves_context_path():  # noqa: ANN001
    import app.api.v1.connectors as connectors

    base = "https://example.atlassian.net/wiki"
    webui = "/spaces/DOCS/pages/12345/Hello"
    out = connectors._confluence_join_webui(base=base, webui=webui)
    assert out == "https://example.atlassian.net/wiki/spaces/DOCS/pages/12345/Hello"


def test_confluence_api_base_url_normalizes_rest_api_suffix():  # noqa: ANN001
    import app.api.v1.connectors as connectors

    assert connectors._confluence_api_base_url("https://c.example.com/wiki") == "https://c.example.com/wiki/rest/api"
    assert connectors._confluence_api_base_url("https://c.example.com/wiki/") == "https://c.example.com/wiki/rest/api"
    assert connectors._confluence_api_base_url("https://c.example.com/rest/api") == "https://c.example.com/rest/api"


def test_confluence_ingest_method_defaults_to_api_view():  # noqa: ANN001
    import app.api.v1.connectors as connectors

    assert connectors._confluence_ingest_method({}) == "api_view"
    assert connectors._confluence_ingest_method({"ingest_method": "api_view"}) == "api_view"
    assert connectors._confluence_ingest_method({"ingest_method": "webui"}) == "webui"
    assert connectors._confluence_ingest_method({"ingest_method": "WEBUI"}) == "webui"
    assert connectors._confluence_ingest_method({"ingest_method": "nope"}) == "api_view"


def test_confluence_attachment_limits_defaults_and_clamps():  # noqa: ANN001
    import app.api.v1.connectors as connectors

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
    import app.api.v1.connectors as connectors

    base = "https://example.atlassian.net/wiki"
    download = "/download/attachments/12345/file.pdf"
    out = connectors._confluence_attachment_download_url(base=base, download=download)
    assert out == "https://example.atlassian.net/wiki/download/attachments/12345/file.pdf"


def test_confluence_extract_attachments_builds_download_urls_and_bounds():  # noqa: ANN001
    import app.api.v1.connectors as connectors

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
    import app.api.v1.connectors as connectors

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
    import app.api.v1.connectors as connectors

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
