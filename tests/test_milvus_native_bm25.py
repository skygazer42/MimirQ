import json
from copy import deepcopy
from uuid import uuid4

import pytest
from langchain_core.documents import Document


def _schema():
    schema = {
        "description": "ragvia_native_bm25_v1:chinese",
        "fields": [
            {"name": name}
            for name in ("id", "chunk_id", "tenant_id", "dataset_id", "document_id", "content", "metadata", "sparse")
        ],
        "functions": [
            {"name": "content_bm25", "type": 1, "input_field_names": ["content"], "output_field_names": ["sparse"]}
        ],
    }
    next(field for field in schema["fields"] if field["name"] == "content")["params"] = {
        "enable_analyzer": True,
        "analyzer_params": '{"type":"chinese"}',
    }
    return schema


class Client:
    def __init__(self, *, exists=True, hits=()):
        self.exists = exists
        self.hits = list(hits)
        self.calls = []
        self.schema = _schema()

    def has_collection(self, **kwargs):
        self.calls.append(("has", kwargs))
        return self.exists

    def describe_collection(self, **kwargs):
        self.calls.append(("describe", kwargs))
        return deepcopy(self.schema)

    def create_collection(self, **kwargs):
        self.calls.append(("create", kwargs))
        self.exists = True

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return [deepcopy(self.hits[: kwargs["limit"]])]

    def upsert(self, **kwargs):
        self.calls.append(("upsert", kwargs))
        return {"upsert_count": len(kwargs["data"])}

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return {"delete_count": 2}


def _owner(client):
    from app.storage.bm25.milvus import MilvusBM25Store

    return MilvusBM25Store(client=client, collection_name="test_bm25")


def _hit(tenant, dataset, document, *, tag="allowed", score=2.5):
    chunk = str(uuid4())
    return {
        "id": f"{tenant}:{chunk}",
        "distance": score,
        "entity": {
            "chunk_id": chunk,
            "tenant_id": str(tenant),
            "dataset_id": str(dataset),
            "document_id": str(document),
            "content": "indexed searchable text",
            "metadata": {
                "tenant_id": str(tenant),
                "dataset_id": str(dataset),
                "document_id": str(document),
                "tag": tag,
            },
        },
    }


def test_raw_text_search_pushes_tenant_dataset_and_document_scope_to_milvus():
    tenant, dataset, document = uuid4(), uuid4(), uuid4()
    client = Client(hits=[_hit(tenant, dataset, document)])
    result = _owner(client).search(
        "中文 ACME-123", tenant_id=tenant, dataset_ids=(dataset,), document_ids=(document,), top_k=3
    )
    call = next(value for name, value in client.calls if name == "search")
    assert call["data"] == ["中文 ACME-123"]
    assert call["anns_field"] == "sparse"
    assert call["search_params"]["metric_type"] == "BM25"
    assert str(tenant) in call["filter"] and str(dataset) in call["filter"] and str(document) in call["filter"]
    assert result[0]["score"] == 2.5
    assert result[0]["metadata"]["bm25_score_raw"] == 2.5
    assert not any(name == "create" for name, _ in client.calls)


def test_metadata_trimming_refills_the_bounded_native_candidate_window(monkeypatch):
    from app.core.config import settings

    tenant, dataset, document = uuid4(), uuid4(), uuid4()
    hits = [_hit(tenant, dataset, document, tag="denied") for _ in range(35)]
    hits += [_hit(tenant, dataset, document)]
    client = Client(hits=hits)
    monkeypatch.setattr(settings, "MILVUS_BM25_MAX_CANDIDATES", 64, raising=False)
    result = _owner(client).search("text", tenant_id=tenant, metadata_filter={"tag": "allowed"}, top_k=1)
    calls = [value for name, value in client.calls if name == "search"]
    assert len(calls) == 2
    assert all(call["limit"] <= 64 for call in calls)
    assert result[0]["chunk_id"] == hits[-1]["entity"]["chunk_id"]


def test_index_metadata_cannot_override_native_tenant_or_requested_scope():
    tenant, dataset, document = uuid4(), uuid4(), uuid4()
    valid = _hit(tenant, dataset, document)
    forged = _hit(uuid4(), dataset, document)
    forged["entity"]["metadata"]["tenant_id"] = str(tenant)
    other_dataset = _hit(tenant, uuid4(), document)
    result = _owner(Client(hits=[forged, other_dataset, valid])).search(
        "text", tenant_id=tenant, dataset_ids=(dataset,), top_k=5
    )
    assert [row["chunk_id"] for row in result] == [valid["entity"]["chunk_id"]]


def test_upsert_uses_stable_tenant_prefixed_ids_and_sends_no_sparse_vectors():
    tenant, dataset, document, chunk = uuid4(), uuid4(), uuid4(), uuid4()
    owner = _owner(Client())
    doc = Document(
        id=str(chunk),
        page_content="原始正文",
        metadata={"tenant_id": str(tenant), "dataset_id": str(dataset), "document_id": str(document)},
    )
    owner.upsert([doc], tenant_id=tenant)
    row = next(value for name, value in owner._client.calls if name == "upsert")["data"][0]
    assert row["id"] == f"{tenant}:{chunk}"
    assert row["chunk_id"] == str(chunk)
    assert row["content"] == "原始正文"
    assert "sparse" not in row


def test_cross_tenant_write_fails_before_any_client_mutation():
    tenant = uuid4()
    client = Client()
    doc = Document(
        id=str(uuid4()), page_content="text", metadata={"tenant_id": str(uuid4()), "document_id": str(uuid4())}
    )
    with pytest.raises(ValueError, match="tenant"):
        _owner(client).upsert([doc], tenant_id=tenant)
    assert not client.calls


def test_native_schema_has_chinese_analyzer_bm25_function_and_sparse_inverted_index():
    pytest.importorskip("pymilvus")
    from app.storage.bm25.milvus import build_milvus_bm25_indexes, build_milvus_bm25_schema

    schema = build_milvus_bm25_schema().to_dict()
    fields = {field["name"]: field for field in schema["fields"]}
    assert fields["content"]["params"]["enable_analyzer"] is True
    assert json.loads(fields["content"]["params"]["analyzer_params"]) == {"type": "chinese"}
    assert schema["functions"][0]["input_field_names"] == ["content"]
    assert schema["functions"][0]["output_field_names"] == ["sparse"]
    indexes = list(build_milvus_bm25_indexes())
    assert indexes[0].to_dict()["index_type"] == "SPARSE_INVERTED_INDEX"
    assert indexes[0].to_dict()["metric_type"] == "BM25"


def test_missing_collection_reads_raise_actionable_error_and_never_create_it():
    from app.storage.bm25.milvus import BM25IndexNotReadyError

    client = Client(exists=False)
    with pytest.raises(BM25IndexNotReadyError, match="backfill"):
        _owner(client).search("text", tenant_id=uuid4())
    assert not any(name == "create" for name, _ in client.calls)


def test_incompatible_existing_collection_is_not_replaced():
    from app.storage.bm25.milvus import BM25IndexNotReadyError

    client = Client()
    client.schema["description"] = "old_schema"
    with pytest.raises(BM25IndexNotReadyError, match="schema"):
        _owner(client).search("text", tenant_id=uuid4())
    assert not any(name == "create" for name, _ in client.calls)


def test_native_service_failure_propagates_without_unfiltered_retry():
    client = Client()
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("milvus unavailable")

    client.search = fail
    with pytest.raises(RuntimeError, match="milvus unavailable"):
        _owner(client).search("text", tenant_id=uuid4(), metadata_filter={"dataset_id": str(uuid4())})
    assert len(calls) == 1 and "tenant_id" in calls[0]["filter"]


def test_identity_scoped_delete_cannot_broaden_tenant_or_omit_scope():
    tenant, dataset = uuid4(), uuid4()
    client = Client()
    owner = _owner(client)
    with pytest.raises(ValueError, match="filter"):
        owner.delete(tenant_id=tenant, metadata_filter={})
    count = owner.delete(tenant_id=tenant, metadata_filter={"dataset_id": str(dataset)})
    call = next(value for name, value in client.calls if name == "delete")
    assert count == 2
    assert str(tenant) in call["filter"] and str(dataset) in call["filter"]


def test_empty_query_performs_no_native_io():
    client = Client()
    assert _owner(client).search(" ", tenant_id=uuid4()) == []
    assert client.calls == []


@pytest.mark.parametrize("corruption", ["analyzer", "function"])
def test_existing_schema_marker_does_not_hide_incompatible_native_configuration(corruption):
    from app.storage.bm25.milvus import BM25IndexNotReadyError

    client = Client()
    if corruption == "analyzer":
        next(field for field in client.schema["fields"] if field["name"] == "content")["params"]["analyzer_params"] = (
            '{"type":"standard"}'
        )
    else:
        client.schema["functions"][0]["type"] = 0
    with pytest.raises(BM25IndexNotReadyError, match="schema"):
        _owner(client).search("text", tenant_id=uuid4())


def test_delete_from_an_absent_index_is_an_explicit_noop():
    client = Client(exists=False)
    assert _owner(client).delete(tenant_id=uuid4(), metadata_filter={"document_id": str(uuid4())}) == 0
    assert not any(name in {"create", "delete"} for name, _ in client.calls)


def test_true_or_branch_does_not_push_an_optional_dataset_constraint():
    tenant, dataset, document = uuid4(), uuid4(), uuid4()
    client = Client(hits=[_hit(tenant, dataset, document)])
    result = _owner(client).search(
        "text", tenant_id=tenant, metadata_filter={"$or": [{}, {"dataset_id": str(uuid4())}]}
    )
    assert len(result) == 1
    call = next(value for name, value in client.calls if name == "search")
    assert call["filter"] == f'tenant_id == "{tenant}"'


@pytest.mark.parametrize("delete_fails", [False, True])
def test_complex_filter_delete_trims_foreign_references_and_closes_iterator(delete_fails):
    from types import SimpleNamespace

    tenant, dataset, document = uuid4(), uuid4(), uuid4()
    allowed = _hit(tenant, dataset, document)
    denied = _hit(tenant, dataset, document, tag="denied")
    foreign = _hit(uuid4(), dataset, document)
    rows = [{"id": hit["id"], **hit["entity"]} for hit in [allowed, denied, foreign]]
    batches = iter([rows, []])
    closed = []
    iterator = SimpleNamespace(next=lambda: next(batches), close=lambda: closed.append(True))
    client = Client()
    client.query_iterator = lambda **kwargs: iterator
    writes = []

    def delete(**kwargs):
        writes.append(kwargs)
        if delete_fails:
            raise RuntimeError("native delete unavailable")
        return {"delete_count": len(kwargs["ids"])}

    client.delete = delete
    owner = _owner(client)
    if delete_fails:
        with pytest.raises(RuntimeError, match="native delete unavailable"):
            owner.delete(tenant_id=tenant, metadata_filter={"tag": "allowed"})
    else:
        assert owner.delete(tenant_id=tenant, metadata_filter={"tag": "allowed"}) == 1
    assert writes[0]["ids"] == [allowed["id"]]
    assert "filter" not in writes[0]
    assert closed == [True]
