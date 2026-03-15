from __future__ import annotations

import uuid
from datetime import UTC, datetime


def test_delta_sync_connector_documents_acl_by_source_url_updates_docs_and_provenance(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    requested_by = "delta-sync-actor"

    class _Doc:
        def __init__(self, idx: int) -> None:
            self.id = uuid.uuid4()
            self.doc_metadata = {"idx": idx}

    docs = [_Doc(1), _Doc(2), _Doc(3)]

    applied: list[uuid.UUID] = []

    def _apply_stub(_db, *, doc, **_k):  # noqa: ANN001
        applied.append(doc.id)

    monkeypatch.setattr(connectors, "_apply_document_access_from_config", _apply_stub, raising=True)

    class _DummyQuery:
        def __init__(self, docs_in):  # noqa: ANN001
            self._docs = list(docs_in or [])
            self._limit: int | None = None

        def join(self, *_a, **_k):  # noqa: ANN001
            return self

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def distinct(self, *_a, **_k):  # noqa: ANN001
            return self

        def order_by(self, *_a, **_k):  # noqa: ANN001
            return self

        def limit(self, n: int):  # noqa: ANN001
            self._limit = int(n)
            return self

        def yield_per(self, _n: int):  # noqa: ANN001, ANN201
            if self._limit is not None and self._limit > 0:
                return list(self._docs)[: self._limit]
            return list(self._docs)

    class _DummyDB:
        def __init__(self, docs_in):  # noqa: ANN001
            self._docs = list(docs_in or [])

        def query(self, _model):  # noqa: ANN001
            return _DummyQuery(self._docs)

    dummy_db = _DummyDB(docs)
    prov = {"schema": "mimirq.document_acl_provenance.v1", "test": True}

    updated = connectors._delta_sync_connector_documents_acl_by_source_url(
        dummy_db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="drive_files",
        source_url="https://example.com/source",
        requested_by=requested_by,
        access={"mode": "partial_members", "partial_group_list": [str(uuid.uuid4())]},
        acl_provenance=prov,
    )

    assert updated == 3
    assert applied == [d.id for d in docs]
    assert all((d.doc_metadata or {}).get("acl_provenance") == prov for d in docs)


def test_delta_sync_confluence_documents_acl_by_page_id_fallback_scan_filters_docs(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    requested_by = "delta-sync-actor"

    base_url = "https://example.atlassian.net/wiki"
    space_key = "DOCS"
    page_id = "123"

    class _Doc:
        def __init__(self, connector_id: str, pid: str) -> None:
            self.id = uuid.uuid4()
            self.doc_metadata = {
                "connector": {
                    "connector_id": connector_id,
                    "base_url": base_url,
                    "space_key": space_key,
                    "page_id": pid,
                }
            }

    doc_match_page = _Doc("confluence_space", "123")
    doc_match_attachment = _Doc("confluence_space", "123")
    doc_other = _Doc("confluence_space", "999")
    docs = [doc_match_page, doc_match_attachment, doc_other]

    applied: list[uuid.UUID] = []

    def _apply_stub(_db, *, doc, **_k):  # noqa: ANN001
        applied.append(doc.id)

    monkeypatch.setattr(connectors, "_apply_document_access_from_config", _apply_stub, raising=True)

    class _DummyQuery:
        def __init__(self, docs_in):  # noqa: ANN001
            self._docs = list(docs_in or [])

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def order_by(self, *_a, **_k):  # noqa: ANN001
            return self

        def limit(self, _n: int):  # noqa: ANN001
            return self

        def all(self):  # noqa: ANN201
            return list(self._docs)

    class _DummyQueryRaise(_DummyQuery):
        def yield_per(self, _n: int):  # noqa: ANN001, ANN201
            raise RuntimeError("simulate jsonb query failure")

    class _DummyDB:
        def __init__(self, docs_in):  # noqa: ANN001
            self._docs = list(docs_in or [])
            self._calls = 0

        def query(self, _model):  # noqa: ANN001
            self._calls += 1
            if self._calls == 1:
                return _DummyQueryRaise(self._docs)
            return _DummyQuery(self._docs)

    dummy_db = _DummyDB(docs)
    prov = {"schema": "mimirq.document_acl_provenance.v1", "test": True}

    updated = connectors._delta_sync_confluence_documents_acl_by_page_id(
        dummy_db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        base_url=base_url,
        space_key=space_key,
        page_id=page_id,
        requested_by=requested_by,
        access={"mode": "partial_members", "partial_group_list": [str(uuid.uuid4())]},
        acl_provenance=prov,
        max_docs_scan=10,
    )

    assert updated == 2
    assert applied == [doc_match_page.id, doc_match_attachment.id]
    assert doc_match_page.doc_metadata.get("acl_provenance") == prov
    assert doc_match_attachment.doc_metadata.get("acl_provenance") == prov
    assert doc_other.doc_metadata.get("acl_provenance") is None


def test_soft_disable_connector_documents_by_source_url_marks_docs_disabled(monkeypatch):  # noqa: ANN001
    import app.api.v1.connectors as connectors

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Doc:
        def __init__(self, idx: int) -> None:
            self.id = uuid.uuid4()
            self.doc_metadata = {"idx": idx}
            self.disabled_at = None

    docs = [_Doc(1), _Doc(2)]

    class _DummyQuery:
        def __init__(self, docs_in):  # noqa: ANN001
            self._docs = list(docs_in or [])
            self._limit: int | None = None

        def join(self, *_a, **_k):  # noqa: ANN001
            return self

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def distinct(self, *_a, **_k):  # noqa: ANN001
            return self

        def order_by(self, *_a, **_k):  # noqa: ANN001
            return self

        def limit(self, n: int):  # noqa: ANN001
            self._limit = int(n)
            return self

        def yield_per(self, _n: int):  # noqa: ANN001, ANN201
            if self._limit is not None and self._limit > 0:
                return list(self._docs)[: self._limit]
            return list(self._docs)

    class _DummyDB:
        def __init__(self, docs_in):  # noqa: ANN001
            self._docs = list(docs_in or [])

        def query(self, _model):  # noqa: ANN001
            return _DummyQuery(self._docs)

    now = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    dummy_db = _DummyDB(docs)
    monkeypatch.setattr(connectors, "_now", lambda: now, raising=True)

    updated = connectors._soft_disable_connector_documents_by_source_url(
        dummy_db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="github_repo",
        source_url="https://raw.githubusercontent.com/acme/docs/main/obsolete.md",
    )

    assert updated == 2
    assert all(doc.disabled_at == now for doc in docs)
