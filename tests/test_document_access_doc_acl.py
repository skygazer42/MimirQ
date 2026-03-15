from __future__ import annotations

from uuid import uuid4


class _FakeQuery:
    def __init__(self, rows):  # noqa: ANN001
        self._rows = list(rows)

    def filter(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def all(self):  # noqa: ANN201
        return list(self._rows)

    def first(self):  # noqa: ANN201
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, *, docs_rows, allowlist_rows, group_allowlist_rows, membership_rows):  # noqa: ANN001
        self._docs_rows = list(docs_rows)
        self._allowlist_rows = list(allowlist_rows)
        self._group_allowlist_rows = list(group_allowlist_rows)
        self._membership_rows = list(membership_rows)

    def query(self, *args, **_kwargs):  # noqa: ANN001
        # Distinguish document_id allowlist lookup vs document rows query.
        if len(args) == 1:
            col = args[0]
            if getattr(col, "key", None) == "document_id" and getattr(getattr(col, "class_", None), "__name__", None) == "DocumentPermission":
                return _FakeQuery(self._allowlist_rows)
            if getattr(col, "key", None) == "document_id" and getattr(getattr(col, "class_", None), "__name__", None) == "DocumentGroupPermission":
                return _FakeQuery(self._group_allowlist_rows)
            if getattr(col, "key", None) == "group_id" and getattr(getattr(col, "class_", None), "__name__", None) == "TenantGroupMember":
                return _FakeQuery(self._membership_rows)
        return _FakeQuery(self._docs_rows)


def test_get_allowed_document_id_sets_enforces_doc_acl_and_dataset_owner_bypass(monkeypatch):  # noqa: ANN001
    import app.services.document_access as da

    tenant_id = uuid4()
    dataset1 = uuid4()
    dataset2 = uuid4()
    doc_owner_only = uuid4()
    doc_partial = uuid4()
    doc_owner_only_dataset_owner_bypass = uuid4()
    doc_legacy_owner_only = uuid4()

    # account "bob" can read dataset1/dataset2 at dataset-level, but should be restricted by doc ACL.
    docs_rows = [
        (doc_owner_only, dataset1, "only_me", "alice"),
        (doc_partial, dataset1, "partial_members", "alice"),
        (doc_owner_only_dataset_owner_bypass, dataset2, "only_me", "alice"),
        (doc_legacy_owner_only, None, "only_me", "alice"),
    ]
    allowlist_rows = [(doc_partial,)]  # bob is explicitly allowed on doc_partial

    class _DS:
        def __init__(self, owner_id: str):  # noqa: ANN001
            self.owner_id = owner_id

    dataset_map = {dataset1: _DS("someone"), dataset2: _DS("boss")}
    allowed_dataset_ids = {dataset1, dataset2}

    monkeypatch.setattr(
        da,
        "_resolve_allowed_dataset_ids",
        lambda _db, _tenant_id, _account_id, _dataset_ids: (dataset_map, allowed_dataset_ids),
        raising=True,
    )

    db = _FakeSession(docs_rows=docs_rows, allowlist_rows=allowlist_rows, group_allowlist_rows=[], membership_rows=[])
    allowed, missing = da.get_allowed_document_id_sets(
        db,
        tenant_id,
        "bob",
        [doc_owner_only, doc_partial, doc_owner_only_dataset_owner_bypass, doc_legacy_owner_only],
        check_member=False,
    )
    assert not missing
    assert doc_partial in allowed
    assert doc_owner_only not in allowed
    assert doc_owner_only_dataset_owner_bypass not in allowed
    assert doc_legacy_owner_only not in allowed

    # Dataset owner bypass: "boss" should be allowed to read docs in dataset2 regardless of doc ACL.
    db2 = _FakeSession(
        docs_rows=[(doc_owner_only_dataset_owner_bypass, dataset2, "only_me", "alice")],
        allowlist_rows=[],
        group_allowlist_rows=[],
        membership_rows=[],
    )
    allowed2, missing2 = da.get_allowed_document_id_sets(
        db2,
        tenant_id,
        "boss",
        [doc_owner_only_dataset_owner_bypass],
        check_member=False,
    )
    assert not missing2
    assert doc_owner_only_dataset_owner_bypass in allowed2


def test_get_allowed_document_id_sets_allows_doc_acl_via_group_allowlist(monkeypatch):  # noqa: ANN001
    import app.services.document_access as da

    tenant_id = uuid4()
    dataset1 = uuid4()
    doc_partial = uuid4()
    group_id = uuid4()

    docs_rows = [
        (doc_partial, dataset1, "partial_members", "alice"),
    ]
    allowlist_rows = []  # no direct member allowlist
    membership_rows = [(group_id,)]  # bob is in a group
    group_allowlist_rows = [(doc_partial,)]  # group grants access to doc_partial

    class _DS:
        def __init__(self, owner_id: str):  # noqa: ANN001
            self.owner_id = owner_id

    dataset_map = {dataset1: _DS("someone")}
    allowed_dataset_ids = {dataset1}

    monkeypatch.setattr(
        da,
        "_resolve_allowed_dataset_ids",
        lambda _db, _tenant_id, _account_id, _dataset_ids: (dataset_map, allowed_dataset_ids),
        raising=True,
    )

    db = _FakeSession(
        docs_rows=docs_rows,
        allowlist_rows=allowlist_rows,
        group_allowlist_rows=group_allowlist_rows,
        membership_rows=membership_rows,
    )
    allowed, missing = da.get_allowed_document_id_sets(
        db,
        tenant_id,
        "bob",
        [doc_partial],
        check_member=False,
    )
    assert not missing
    assert doc_partial in allowed
