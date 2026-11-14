from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.api.schemas.dataset import DatasetEmbeddingDefaults
from app.api.schemas.regression import RagasRegressionRunCreateRequest
from app.rag.kg import pipeline
from app.rag.kg.provenance import build_kg_path_provenance
from app.rag.kg.search.cache import KGSearchCache, build_kg_community_summary_cache_key, build_kg_search_cache_key


def test_kg_cache_distinguishes_unselected_and_empty_document_scope() -> None:
    args = dict(tenant_id="tenant", account_id="reader", dataset_id="dataset", query="policy", search_config={})
    assert build_kg_search_cache_key(**args, document_ids=None) != build_kg_search_cache_key(**args, document_ids=[])


@pytest.mark.parametrize("document_ids", [None, []])
def test_new_scope_keys_cannot_read_ambiguous_v2_cache_entries(document_ids) -> None:
    key = build_kg_search_cache_key(
        tenant_id="tenant",
        account_id="reader",
        dataset_id="dataset",
        query="policy",
        search_config={},
        document_ids=document_ids,
    )
    assert key != "kgsearch:tenant:43811f9eb306f22951a486d5e9f9abc8"


def test_community_cache_preserves_empty_document_scope() -> None:
    args = dict(tenant_id="tenant", dataset_id="dataset", community_id="community", query="policy")
    assert build_kg_community_summary_cache_key(**args, document_ids=None) != build_kg_community_summary_cache_key(
        **args, document_ids=[]
    )


@pytest.mark.asyncio
async def test_denied_document_scope_cannot_reuse_cached_dataset_results(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class Engine:
        async def search(self, **kwargs):
            calls.append(kwargs)
            return {"chunks": ["authorized-dataset-result"] if kwargs["document_ids"] is None else []}

    monkeypatch.setattr(pipeline, "_load_engine", lambda: Engine())
    monkeypatch.setattr(pipeline, "kg_search_cache", KGSearchCache())
    monkeypatch.setattr(pipeline, "_kg_search_cache_settings", lambda: (True, 60, 10))
    monkeypatch.setattr(pipeline, "_resolve_search_pipeline_fingerprint", lambda **_kwargs: "dataset-version")
    args = dict(query="policy", tenant_id=uuid4(), account_id="reader", dataset_id=uuid4(), query_mode="local")

    assert (await pipeline.kg_search(**args, document_ids=None))["chunks"] == ["authorized-dataset-result"]
    assert (await pipeline.kg_search(**args, document_ids=[]))["chunks"] == []
    assert len(calls) == 2
    assert calls[1]["document_ids"] == []


@pytest.mark.parametrize("dataset_ids", [[UUID(int=1)], [UUID(int=1), UUID(int=2)]])
@pytest.mark.asyncio
async def test_empty_document_selection_keeps_precedence_over_dataset_fanout(dataset_ids, monkeypatch) -> None:
    calls = []

    class Engine:
        async def search(self, **kwargs):
            calls.append(kwargs)
            return {"chunks": []}

    monkeypatch.setattr(pipeline, "_load_engine", lambda: Engine())
    monkeypatch.setattr(pipeline, "_kg_search_cache_settings", lambda: (False, 0, 0))
    await pipeline.kg_search(
        "policy", tenant_id=uuid4(), account_id="reader", document_ids=[], dataset_ids=dataset_ids, query_mode="local"
    )

    assert len(calls) == 1
    assert calls[0]["document_ids"] == []
    assert calls[0]["dataset_id"] is None


def test_empty_key_entity_selection_produces_no_path_entities() -> None:
    entities = [{"id": str(uuid4()), "type": "organization"}]
    assert build_kg_path_provenance(entities=entities, key_entity_ids=set()) == []
    assert len(build_kg_path_provenance(entities=entities, key_entity_ids=None)) == 1


@pytest.mark.parametrize("field", ["provider", "model", "api_base"])
@pytest.mark.parametrize("value", [0, False, [], {}])
def test_embedding_defaults_do_not_stringify_invalid_input(field, value) -> None:
    with pytest.raises(ValidationError):
        DatasetEmbeddingDefaults(**{field: value})


@pytest.mark.parametrize("value", [0, False, [], {}])
def test_regression_strategy_does_not_hide_invalid_input(value) -> None:
    with pytest.raises(ValidationError):
        RagasRegressionRunCreateRequest(dataset_id=uuid4(), query_rewrite_strategy=value)


def test_blank_optional_request_overrides_still_mean_inherit() -> None:
    assert DatasetEmbeddingDefaults(provider="  ").provider is None
    assert (
        RagasRegressionRunCreateRequest(dataset_id=uuid4(), query_rewrite_strategy="  ").query_rewrite_strategy is None
    )
