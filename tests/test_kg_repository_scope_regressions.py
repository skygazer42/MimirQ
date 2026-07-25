from uuid import UUID, uuid4

import pytest


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

    def _raise_filter(*_args, **_kwargs):  # noqa: ANN001
        raise RuntimeError("dataset scope SQL unavailable")

    monkeypatch.setattr(repo, "filter_event_ids_in_dataset", _raise_filter, raising=True)

    results = repo.search_similar_by_content(
        query_vector=[0.3],
        tenant_id=tenant_id,
        k=1,
        dataset_id=dataset_id,
        account_id="acct-1",
    )

    assert results == []


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
