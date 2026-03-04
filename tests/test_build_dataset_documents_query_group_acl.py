from __future__ import annotations

from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session


def test_build_dataset_documents_query_includes_group_allowlist_subquery(monkeypatch):  # noqa: ANN001
    """
    Regression guard for Wave25 groups:

    Dataset-scoped document queries are used by evidence retrieval and chat flows.
    Ensure the shared helper includes group-based doc allowlists (document_group_permissions)
    in addition to per-user allowlists (document_permissions).
    """
    import app.services.dataset_profile_service as dps

    class _DS:  # noqa: WPS431
        pass

    monkeypatch.setattr(dps.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dps.DatasetService, "get_dataset", lambda *_a, **_k: _DS(), raising=True)
    monkeypatch.setattr(dps.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    engine = create_engine("sqlite:///:memory:")
    db = Session(bind=engine)
    _dataset, query = dps.build_dataset_documents_query(
        db,
        tenant_id=uuid4(),
        account_id="bob",
        dataset_id=uuid4(),
    )

    sql = str(query.statement.compile(dialect=postgresql.dialect()))
    assert "document_permissions" in sql
    assert "document_group_permissions" in sql
    assert "tenant_group_members" in sql

