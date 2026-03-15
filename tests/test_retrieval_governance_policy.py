from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest


def _mk_result(doc_id: uuid.UUID, score: float) -> dict:
    return {
        "content": "chunk",
        "score": float(score),
        "metadata": {"document_id": str(doc_id), "chunk_index": 0},
    }


def test_retrieval_governance_policy_disabled_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retriever as retriever_module

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    r = retriever_module.HybridRetriever(k=5, tenant_id=tenant_id, dataset_id=dataset_id)

    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY", False, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_PREFER_LATEST", False, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED", False, raising=False)

    a = uuid.uuid4()
    b = uuid.uuid4()
    results = [_mk_result(a, 0.5), _mk_result(b, 0.49)]

    stats: dict = {}
    out = r._apply_governance_policy(list(results), stats=stats)
    assert out == results
    assert stats.get("enabled") is False


def test_retrieval_governance_policy_prefer_authority_reorders(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retriever as retriever_module
    from app.models.document import Document as DBDocument

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    a = uuid.uuid4()
    b = uuid.uuid4()

    # Base score prefers `a`, authority should boost `b` above it.
    results = [_mk_result(a, 0.5), _mk_result(b, 0.49)]

    now = datetime(2026, 3, 3, tzinfo=UTC)
    feature_rows = [
        (a, 10, now - timedelta(days=30), now - timedelta(days=30)),
        (b, 90, now - timedelta(days=30), now - timedelta(days=30)),
    ]

    class _DummyQuery:
        def __init__(self, cols):  # noqa: ANN001
            self.cols = cols

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def all(self):  # noqa: ANN001
            # Feature query: (id, authority_level, updated_at, created_at)
            if len(self.cols) >= 2 and self.cols[1] is DBDocument.authority_level:
                return list(feature_rows)
            return []

    class _DummyDB:
        def query(self, *cols):  # noqa: ANN001
            return _DummyQuery(cols)

        def close(self):  # noqa: ANN001
            return None

    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _DummyDB(), raising=True)

    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY", True, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_PREFER_LATEST", False, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED", False, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX", 0.02, raising=False)

    r = retriever_module.HybridRetriever(k=5, tenant_id=tenant_id, dataset_id=dataset_id)
    stats: dict = {}
    out = r._apply_governance_policy(list(results), stats=stats)

    assert [r._get_doc_id(x) for x in out] == [str(b), str(a)]
    assert stats.get("enabled") is True
    assert stats.get("reordered") is True
    assert stats.get("max_boost", 0.0) > 0.0


def test_retrieval_governance_policy_prefer_latest_reorders(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retriever as retriever_module
    from app.models.document import Document as DBDocument

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    fresh = uuid.uuid4()
    stale = uuid.uuid4()

    # Same base score; latest should prefer `fresh`.
    results = [_mk_result(stale, 0.5), _mk_result(fresh, 0.5)]

    now = datetime(2026, 3, 3, tzinfo=UTC)
    feature_rows = [
        (fresh, 0, now, now),
        (stale, 0, now - timedelta(days=200), now - timedelta(days=200)),
    ]

    class _DummyQuery:
        def __init__(self, cols):  # noqa: ANN001
            self.cols = cols

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def all(self):  # noqa: ANN001
            if len(self.cols) >= 2 and self.cols[1] is DBDocument.authority_level:
                return list(feature_rows)
            return []

    class _DummyDB:
        def query(self, *cols):  # noqa: ANN001
            return _DummyQuery(cols)

        def close(self):  # noqa: ANN001
            return None

    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _DummyDB(), raising=True)

    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY", False, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_PREFER_LATEST", True, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED", False, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX", 0.02, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS", 180, raising=False)

    r = retriever_module.HybridRetriever(k=5, tenant_id=tenant_id, dataset_id=dataset_id)
    out = r._apply_governance_policy(list(results))
    assert [r._get_doc_id(x) for x in out][0] == str(fresh)


def test_retrieval_governance_policy_filters_superseded(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retriever as retriever_module
    from app.models.document import Document as DBDocument

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    old = uuid.uuid4()
    other = uuid.uuid4()

    results = [_mk_result(old, 0.5), _mk_result(other, 0.49)]

    sup_rows = [
        # A newer, active-ready doc supersedes `old`.
        (old, "completed", {}, None, None, "published"),
    ]

    class _DummyQuery:
        def __init__(self, cols):  # noqa: ANN001
            self.cols = cols

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def all(self):  # noqa: ANN001
            # Superseded lookup query: (supersedes_document_id, status, doc_metadata, archived_at, disabled_at)
            if len(self.cols) >= 2 and self.cols[0] is DBDocument.supersedes_document_id:
                return list(sup_rows)
            return []

    class _DummyDB:
        def query(self, *cols):  # noqa: ANN001
            return _DummyQuery(cols)

        def close(self):  # noqa: ANN001
            return None

    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _DummyDB(), raising=True)

    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY", False, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_PREFER_LATEST", False, raising=False)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED", True, raising=False)

    r = retriever_module.HybridRetriever(k=5, tenant_id=tenant_id, dataset_id=dataset_id)
    stats: dict = {}
    out = r._apply_governance_policy(list(results), stats=stats)

    assert [r._get_doc_id(x) for x in out] == [str(other)]
    assert stats.get("filtered_superseded") == 1
