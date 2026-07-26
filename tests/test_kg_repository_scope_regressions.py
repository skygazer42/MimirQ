import datetime as _datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

if not hasattr(_datetime, "UTC"):
    _datetime.UTC = _datetime.timezone.utc  # type: ignore[attr-defined]


class _FakeMilvusAdapter:
    def __init__(self, responses: list[list[dict]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def search(self, *, query_vector: list[float], top_k: int, expr: str) -> list[dict]:
        self.calls.append({"query_vector": list(query_vector), "top_k": top_k, "expr": expr})
        if not self._responses:
            return []
        return self._responses.pop(0)


def _event_hit(*, event_id: UUID, document_id: UUID, score: float, tenant_id: UUID) -> dict:
    return {
        "id": str(event_id),
        "score": score,
        "metadata": {
            "id": str(event_id),
            "tenant_id": str(tenant_id),
            "document_id": str(document_id),
            "title": f"title-{event_id}",
            "summary": f"summary-{event_id}",
            "chunk_id": f"chunk-{event_id}",
        },
    }


def _extract_scoped_document_ids(expr: str) -> list[str]:
    marker = "document_id in ["
    start = expr.index(marker) + len(marker)
    end = expr.index("]", start)
    quoted = expr[start:end].strip()
    if not quoted:
        return []
    return [item.strip().strip('"') for item in quoted.split(",")]


def _build_repo(monkeypatch: pytest.MonkeyPatch, *, responses: list[list[dict]]):
    import app.rag.kg.repository as repository_module

    adapter = _FakeMilvusAdapter(responses)
    monkeypatch.setattr(repository_module, "get_milvus_adapter", lambda **_kwargs: adapter, raising=True)
    return repository_module.EventRepository(session=object()), adapter


def test_search_similar_by_content_empty_document_scope_skips_milvus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, adapter = _build_repo(monkeypatch, responses=[[{"id": "unexpected"}]])

    results = repo.search_similar_by_content(
        query_vector=[0.1],
        tenant_id=uuid4(),
        k=3,
        document_ids=[],
    )

    assert results == []
    assert adapter.calls == []


def test_search_similar_by_content_document_scope_filter_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    event_id = uuid4()
    repo, _adapter = _build_repo(
        monkeypatch,
        responses=[[_event_hit(event_id=event_id, document_id=document_id, score=0.9, tenant_id=tenant_id)]],
    )

    def _raise_filter(*_args, **_kwargs):  # noqa: ANN001
        raise RuntimeError("document scope SQL unavailable")

    monkeypatch.setattr(repo, "filter_event_ids_in_documents", _raise_filter, raising=True)

    results = repo.search_similar_by_content(
        query_vector=[0.2],
        tenant_id=tenant_id,
        k=1,
        document_ids=[document_id],
    )

    assert results == []


def test_search_similar_by_content_dataset_scope_filter_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    event_id = uuid4()
    repo, _adapter = _build_repo(
        monkeypatch,
        responses=[[_event_hit(event_id=event_id, document_id=document_id, score=0.8, tenant_id=tenant_id)]],
    )
    monkeypatch.setattr(
        repo,
        "_allowed_document_ids_for_dataset_limited",
        lambda **_kwargs: ([document_id], False),
        raising=True,
    )

    def _raise_filter(*_args, **_kwargs):  # noqa: ANN001
        raise RuntimeError("dataset scope SQL unavailable")

    monkeypatch.setattr(repo, "filter_event_ids_in_documents", _raise_filter, raising=True)

    results = repo.search_similar_by_content(
        query_vector=[0.3],
        tenant_id=tenant_id,
        k=1,
        dataset_id=dataset_id,
        account_id="acct-1",
    )

    assert results == []


def test_search_similar_by_content_dataset_scope_pushes_allowed_document_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_ids = [uuid4() for _ in range(501)]
    duplicate_event_id = uuid4()
    filtered_event_id = uuid4()
    keep_event_id = uuid4()
    keep_second_event_id = uuid4()
    low_event_id = uuid4()

    repo, adapter = _build_repo(
        monkeypatch,
        responses=[
            [
                _event_hit(event_id=low_event_id, document_id=document_ids[2], score=0.71, tenant_id=tenant_id),
                _event_hit(event_id=duplicate_event_id, document_id=document_ids[1], score=0.83, tenant_id=tenant_id),
                _event_hit(event_id=keep_event_id, document_id=document_ids[0], score=0.92, tenant_id=tenant_id),
            ],
            [
                _event_hit(event_id=filtered_event_id, document_id=document_ids[500], score=0.99, tenant_id=tenant_id),
                _event_hit(event_id=duplicate_event_id, document_id=document_ids[500], score=0.95, tenant_id=tenant_id),
                _event_hit(event_id=keep_second_event_id, document_id=document_ids[500], score=0.89, tenant_id=tenant_id),
            ],
        ],
    )
    monkeypatch.setattr(
        repo,
        "_allowed_document_ids_for_dataset_limited",
        lambda **_kwargs: (document_ids, False),
        raising=True,
    )

    seen_candidate_ids: list[str] = []
    expected_tenant_id = tenant_id
    expected_document_ids = document_ids

    def _filter_ids(candidate_event_ids, *, tenant_id, document_ids):  # noqa: ANN001
        assert tenant_id == expected_tenant_id
        assert document_ids == expected_document_ids
        seen_candidate_ids.extend(str(event_id) for event_id in candidate_event_ids)
        return {duplicate_event_id, keep_event_id, keep_second_event_id}

    monkeypatch.setattr(repo, "filter_event_ids_in_documents", _filter_ids, raising=True)

    results = repo.search_similar_by_content(
        query_vector=[0.5],
        tenant_id=tenant_id,
        k=2,
        dataset_id=dataset_id,
        account_id="acct-1",
    )

    assert len(adapter.calls) == 2
    assert adapter.calls[0]["top_k"] == 10
    assert adapter.calls[1]["top_k"] == 10
    assert _extract_scoped_document_ids(adapter.calls[0]["expr"]) == [str(doc_id) for doc_id in document_ids[:500]]
    assert _extract_scoped_document_ids(adapter.calls[1]["expr"]) == [str(document_ids[500])]
    assert seen_candidate_ids == [
        str(filtered_event_id),
        str(duplicate_event_id),
        str(keep_event_id),
        str(keep_second_event_id),
        str(low_event_id),
    ]
    assert [item["event_id"] for item in results] == [str(duplicate_event_id), str(keep_event_id)]
    assert [item["similarity"] for item in results] == pytest.approx([0.95, 0.92])


def test_allowed_document_ids_for_dataset_limited_queries_only_threshold_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import column

    import app.rag.kg.repository as repository_module

    class _FakeScalarResult:
        def __init__(self, rows: list[UUID]) -> None:
            self._rows = rows

        def all(self) -> list[UUID]:
            return list(self._rows)

    class _FakeExecuteResult:
        def __init__(self, rows: list[UUID]) -> None:
            self._rows = rows

        def scalars(self) -> _FakeScalarResult:
            return _FakeScalarResult(self._rows)

    class _FakeDatasetLimitSession:
        def __init__(self, rows: list[UUID]) -> None:
            self._rows = rows
            self.captured_limit: int | None = None

        def execute(self, stmt):  # noqa: ANN001,D401
            self.captured_limit = int(stmt._limit_clause.value)
            return _FakeExecuteResult(self._rows)

    rows = [uuid4(), uuid4(), uuid4()]
    session = _FakeDatasetLimitSession(rows)
    monkeypatch.setattr(repository_module, "get_milvus_adapter", lambda **_kwargs: object(), raising=True)
    repo = repository_module.EventRepository(session=session)
    monkeypatch.setattr(
        repo,
        "_allowed_document_ids_subquery_for_dataset",
        lambda **_kwargs: SimpleNamespace(c=SimpleNamespace(id=column("id"))),
        raising=True,
    )

    allowed_doc_ids, overflowed = repo._allowed_document_ids_for_dataset_limited(
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        account_id="acct-1",
        limit=2,
    )

    assert session.captured_limit == 3
    assert allowed_doc_ids == rows[:2]
    assert overflowed is True


def test_search_similar_by_content_dataset_scope_over_cap_uses_single_tenant_ann_and_acl_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    event_id = uuid4()
    filtered_event_id = uuid4()
    kept_document_id = uuid4()
    filtered_document_id = uuid4()

    repo, adapter = _build_repo(
        monkeypatch,
        responses=[
            [
                _event_hit(event_id=filtered_event_id, document_id=filtered_document_id, score=0.96, tenant_id=tenant_id),
                _event_hit(event_id=event_id, document_id=kept_document_id, score=0.91, tenant_id=tenant_id),
            ],
        ],
    )
    monkeypatch.setattr(
        repo,
        "_allowed_document_ids_for_dataset_limited",
        lambda **_kwargs: ([kept_document_id], True),
        raising=True,
    )
    monkeypatch.setattr(
        repo,
        "_allowed_document_ids_for_dataset",
        lambda **_kwargs: pytest.fail("must not enumerate all dataset document ids"),
        raising=True,
    )
    monkeypatch.setattr(
        repo,
        "filter_event_ids_in_documents",
        lambda *_args, **_kwargs: pytest.fail("overflow path must ACL-filter via dataset SQL"),
        raising=True,
    )

    seen_candidate_ids: list[str] = []

    def _filter_ids(candidate_event_ids, *, tenant_id, dataset_id, account_id):  # noqa: ANN001
        assert tenant_id == tenant_id_expected
        assert dataset_id == dataset_id_expected
        assert account_id == "acct-1"
        seen_candidate_ids.extend(str(candidate_id) for candidate_id in candidate_event_ids)
        return {event_id}

    tenant_id_expected = tenant_id
    dataset_id_expected = dataset_id
    monkeypatch.setattr(repo, "filter_event_ids_in_dataset", _filter_ids, raising=True)

    results = repo.search_similar_by_content(
        query_vector=[0.6],
        tenant_id=tenant_id,
        k=2,
        dataset_id=dataset_id,
        account_id="acct-1",
    )

    assert len(adapter.calls) == 1
    assert adapter.calls[0]["top_k"] == 10
    assert adapter.calls[0]["expr"] == f'tenant_id == "{tenant_id}"'
    assert seen_candidate_ids == [str(filtered_event_id), str(event_id)]
    assert [item["event_id"] for item in results] == [str(event_id)]
    assert [item["similarity"] for item in results] == pytest.approx([0.91])


def test_search_similar_by_content_batches_large_document_scope_and_filters_after_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    document_ids = [uuid4() for _ in range(501)]
    duplicate_event_id = uuid4()
    filtered_event_id = uuid4()
    keep_event_id = uuid4()
    keep_second_event_id = uuid4()
    low_event_id = uuid4()

    repo, adapter = _build_repo(
        monkeypatch,
        responses=[
            [
                _event_hit(event_id=low_event_id, document_id=document_ids[2], score=0.71, tenant_id=tenant_id),
                _event_hit(event_id=duplicate_event_id, document_id=document_ids[1], score=0.83, tenant_id=tenant_id),
                _event_hit(event_id=keep_event_id, document_id=document_ids[0], score=0.92, tenant_id=tenant_id),
            ],
            [
                _event_hit(event_id=filtered_event_id, document_id=document_ids[500], score=0.99, tenant_id=tenant_id),
                _event_hit(event_id=duplicate_event_id, document_id=document_ids[500], score=0.95, tenant_id=tenant_id),
                _event_hit(event_id=keep_second_event_id, document_id=document_ids[500], score=0.89, tenant_id=tenant_id),
            ],
        ],
    )

    seen_candidate_ids: list[str] = []
    expected_tenant_id = tenant_id
    expected_document_ids = document_ids

    def _filter_ids(candidate_event_ids, *, tenant_id, document_ids):  # noqa: ANN001
        assert tenant_id == expected_tenant_id
        assert document_ids == expected_document_ids
        seen_candidate_ids.extend(str(event_id) for event_id in candidate_event_ids)
        return {duplicate_event_id, keep_event_id, keep_second_event_id}

    monkeypatch.setattr(repo, "filter_event_ids_in_documents", _filter_ids, raising=True)

    results = repo.search_similar_by_content(
        query_vector=[0.4],
        tenant_id=tenant_id,
        k=2,
        document_ids=document_ids,
    )

    assert len(adapter.calls) == 2
    assert adapter.calls[0]["top_k"] == 10
    assert adapter.calls[1]["top_k"] == 10
    assert _extract_scoped_document_ids(adapter.calls[0]["expr"]) == [str(doc_id) for doc_id in document_ids[:500]]
    assert _extract_scoped_document_ids(adapter.calls[1]["expr"]) == [str(document_ids[500])]
    assert seen_candidate_ids == [
        str(filtered_event_id),
        str(duplicate_event_id),
        str(keep_event_id),
        str(keep_second_event_id),
        str(low_event_id),
    ]
    assert [item["event_id"] for item in results] == [str(duplicate_event_id), str(keep_event_id)]
    assert [item["similarity"] for item in results] == pytest.approx([0.95, 0.92])


class _FakeQuery:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def filter(self, *_args, **_kwargs):  # noqa: ANN001,D401
        return self

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeAliasSession:
    def __init__(self, redirect_rows: list[object]) -> None:
        self._redirect_rows = redirect_rows

    def query(self, _model):  # noqa: ANN001,D401
        return _FakeQuery(self._redirect_rows)


def test_alias_redirect_resolution_compresses_multi_hop_chains() -> None:
    from app.rag.kg.repository import AliasRepository

    entity_a = uuid4()
    entity_b = uuid4()
    entity_c = uuid4()
    repo = AliasRepository(
        _FakeAliasSession(
            [
                SimpleNamespace(from_entity_id=entity_a, to_entity_id=entity_b),
                SimpleNamespace(from_entity_id=entity_b, to_entity_id=entity_c),
            ]
        )
    )

    resolved = repo._resolve_redirects([entity_a, entity_b], tenant_id=uuid4())

    assert resolved[entity_a] == entity_c
    assert resolved[entity_b] == entity_c


def test_alias_redirect_resolution_breaks_cycles_without_cross_mapping() -> None:
    from app.rag.kg.repository import AliasRepository

    entity_a = uuid4()
    entity_b = uuid4()
    repo = AliasRepository(
        _FakeAliasSession(
            [
                SimpleNamespace(from_entity_id=entity_a, to_entity_id=entity_b),
                SimpleNamespace(from_entity_id=entity_b, to_entity_id=entity_a),
            ]
        )
    )

    resolved = repo._resolve_redirects([entity_a, entity_b], tenant_id=uuid4())

    assert resolved[entity_a] == entity_a
    assert resolved[entity_b] == entity_b


@pytest.mark.parametrize("size", [3, 4])
def test_alias_redirect_resolution_keeps_each_cycle_node_self_mapped(size: int) -> None:
    from app.rag.kg.repository import AliasRepository

    entities = [uuid4() for _ in range(size)]
    redirect_rows = [
        SimpleNamespace(from_entity_id=entities[idx], to_entity_id=entities[(idx + 1) % size])
        for idx in range(size)
    ]
    repo = AliasRepository(_FakeAliasSession(redirect_rows))

    resolved = repo._resolve_redirects(list(reversed(entities)), tenant_id=uuid4())

    assert resolved == {entity_id: entity_id for entity_id in entities}


def test_alias_redirect_resolution_preserves_non_cycle_prefix_into_cycle_entry() -> None:
    from app.rag.kg.repository import AliasRepository

    entry = uuid4()
    second = uuid4()
    third = uuid4()
    prefix = uuid4()
    repo = AliasRepository(
        _FakeAliasSession(
            [
                SimpleNamespace(from_entity_id=prefix, to_entity_id=entry),
                SimpleNamespace(from_entity_id=entry, to_entity_id=second),
                SimpleNamespace(from_entity_id=second, to_entity_id=third),
                SimpleNamespace(from_entity_id=third, to_entity_id=entry),
            ]
        )
    )

    resolved = repo._resolve_redirects([prefix, entry, second, third], tenant_id=uuid4())

    assert resolved[prefix] == entry
    assert resolved[entry] == entry
    assert resolved[second] == second
    assert resolved[third] == third
