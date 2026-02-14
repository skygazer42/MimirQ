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
