from __future__ import annotations

import uuid
from datetime import UTC, datetime


def _run(*, monkeypatch, mode: str, order_by: str, order_dir: str):  # noqa: ANN001
    import app.api.v1.governance as governance_module
    from app.models.document import Document as DBDocument

    class _DummyQuery:
        def __init__(self) -> None:
            self.filters = []
            self.order_by_args = []
            self.offset_arg = None
            self.limit_arg = None

        def filter(self, *args, **_kwargs):  # noqa: ANN001
            self.filters.extend(args)
            return self

        def order_by(self, *args, **_kwargs):  # noqa: ANN001
            self.order_by_args = list(args)
            return self

        def offset(self, *args, **_kwargs):  # noqa: ANN001
            self.offset_arg = args[0] if args else None
            return self

        def limit(self, *args, **_kwargs):  # noqa: ANN001
            self.limit_arg = args[0] if args else None
            return self

        def count(self):  # noqa: ANN001
            return 0

        def all(self):  # noqa: ANN001
            return []

    dummy_query = _DummyQuery()

    class _DummyDB:
        def query(self, model):  # noqa: ANN001
            assert model is DBDocument
            return dummy_query

    # Bypass membership/permission enforcement; we only validate query construction here.
    monkeypatch.setattr(governance_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(governance_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(governance_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    resp = governance_module.list_stale_documents_by_dataset(
        dataset_id=uuid.uuid4(),
        mode=mode,  # type: ignore[arg-type]
        due_within_days=7,
        due_before=None,
        as_of=datetime(2026, 3, 3, 0, 0, tzinfo=UTC),
        include_inactive=False,
        skip=5,
        limit=10,
        order_by=order_by,  # type: ignore[arg-type]
        order_dir=order_dir,  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        account_id="acct",
        db=_DummyDB(),  # type: ignore[arg-type]
    )
    return dummy_query, resp


def test_governance_stale_documents_has_deterministic_id_tie_breaker(monkeypatch):  # noqa: ANN001
    q, _ = _run(monkeypatch=monkeypatch, mode="all", order_by="review_due_at", order_dir="desc")
    assert len(q.order_by_args) == 2
    assert "documents.review_due_at" in str(q.order_by_args[0])
    assert "DESC" in str(q.order_by_args[0]).upper()
    assert "documents.id" in str(q.order_by_args[1])
    assert "ASC" in str(q.order_by_args[1]).upper()


def test_governance_stale_documents_filters_on_review_due_at(monkeypatch):  # noqa: ANN001
    q, _ = _run(monkeypatch=monkeypatch, mode="all", order_by="review_due_at", order_dir="asc")
    assert q.filters, "expected endpoint to apply filters"
    text = "\n".join([str(f) for f in q.filters])
    assert "documents.review_due_at" in text
    assert "IS NOT NULL" in text.upper()


def test_governance_stale_documents_mode_overdue_uses_leq_filter(monkeypatch):  # noqa: ANN001
    q, _ = _run(monkeypatch=monkeypatch, mode="overdue", order_by="review_due_at", order_dir="asc")
    text = "\n".join([str(f) for f in q.filters])
    assert "<=" in text
    assert "documents.review_due_at" in text


def test_governance_stale_documents_mode_due_soon_uses_gt_and_leq_filters(monkeypatch):  # noqa: ANN001
    q, _ = _run(monkeypatch=monkeypatch, mode="due_soon", order_by="review_due_at", order_dir="asc")
    text = "\n".join([str(f) for f in q.filters])
    assert ">" in text
    assert "<=" in text
    assert "documents.review_due_at" in text


def test_governance_stale_documents_applies_offset_and_limit(monkeypatch):  # noqa: ANN001
    q, resp = _run(monkeypatch=monkeypatch, mode="all", order_by="filename", order_dir="asc")
    assert q.offset_arg == 5
    assert q.limit_arg == 10
    assert resp.skip == 5
    assert resp.limit == 10
    assert resp.items == []

