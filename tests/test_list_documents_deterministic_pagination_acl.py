import asyncio
import uuid


def _collect_binds(expr):  # noqa: ANN001
    """
    Collect SQLAlchemy BindParameter (key, value) pairs from an expression tree.

    We use this to assert the list_documents ACL filter keeps stable, explicit
    policy literals (e.g. 'partial_members', ['inherit', 'all_team_members']).
    """
    from sqlalchemy.sql.elements import BindParameter

    out = []
    seen = set()

    def walk(node):  # noqa: ANN001
        nid = id(node)
        if nid in seen:
            return
        seen.add(nid)
        if isinstance(node, BindParameter):
            out.append((str(node.key), node.value))
        for child in node.get_children():
            walk(child)

    walk(expr)
    return out


def _run_list_documents(*, monkeypatch, order_by: str, order_dir: str):  # noqa: ANN001
    from app.api.v1.documents import list_documents
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

    # Bypass permission enforcement; we only care about query construction here.
    import app.api.v1.documents as documents_module

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    asyncio.run(
        list_documents(
            skip=0,
            limit=20,
            status=None,
            lifecycle="active",
            dataset_id=uuid.uuid4(),
            file_type=None,
            owner_id=None,
            q=None,
            source_path_prefix=None,
            order_by=order_by,
            order_dir=order_dir,
            tenant_id=uuid.uuid4(),
            account_id="acct",
            db=_DummyDB(),  # type: ignore[arg-type]
        )
    )

    return dummy_query


def test_list_documents_has_deterministic_pagination_tie_breaker(monkeypatch):  # noqa: ANN001
    """
    Ensure the API keeps pagination deterministic by always ordering by id as a tie-breaker.
    """
    dummy_query = _run_list_documents(monkeypatch=monkeypatch, order_by="created_at", order_dir="desc")
    assert len(dummy_query.order_by_args) == 2
    assert "documents.created_at" in str(dummy_query.order_by_args[0])
    assert "DESC" in str(dummy_query.order_by_args[0]).upper()
    assert "documents.id" in str(dummy_query.order_by_args[1])
    assert "ASC" in str(dummy_query.order_by_args[1]).upper()


def test_list_documents_order_dir_does_not_flip_id_tie_breaker(monkeypatch):  # noqa: ANN001
    dummy_query = _run_list_documents(monkeypatch=monkeypatch, order_by="filename", order_dir="asc")
    assert len(dummy_query.order_by_args) == 2
    assert "documents.filename" in str(dummy_query.order_by_args[0])
    assert "ASC" in str(dummy_query.order_by_args[0]).upper()
    assert "documents.id" in str(dummy_query.order_by_args[1])
    assert "ASC" in str(dummy_query.order_by_args[1]).upper()

    dummy_query = _run_list_documents(monkeypatch=monkeypatch, order_by="filename", order_dir="desc")
    assert len(dummy_query.order_by_args) == 2
    assert "documents.filename" in str(dummy_query.order_by_args[0])
    assert "DESC" in str(dummy_query.order_by_args[0]).upper()
    assert "documents.id" in str(dummy_query.order_by_args[1])
    assert "ASC" in str(dummy_query.order_by_args[1]).upper()


def test_list_documents_acl_filter_contains_expected_policy_literals(monkeypatch):  # noqa: ANN001
    dummy_query = _run_list_documents(monkeypatch=monkeypatch, order_by="created_at", order_dir="desc")
    assert dummy_query.filters, "expected list_documents to apply filters"

    binds = []
    for f in dummy_query.filters:
        binds.extend(_collect_binds(f))

    values = [v for _k, v in binds]

    assert any(isinstance(v, list) and set(v) == {"inherit", "all_team_members"} for v in values)
    assert "partial_members" in values
    assert any("account_id" in k and v == "acct" for k, v in binds)
    assert any("owner_id" in k and v == "acct" for k, v in binds)
