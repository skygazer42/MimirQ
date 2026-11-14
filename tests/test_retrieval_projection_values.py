from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides
from app.rag.retrieval.context_expansion import _neighbor_item
from app.rag.retrieval.hybrid.lexical import LexicalDBMixin
from app.rag.retrieval.hybrid.metadata_scope import lexical_dataset_scope
from app.rag.retrieval.orchestration.query_options import parse_model_query_overrides, resolve_model_query_settings
from app.rag.retrieval.sibling_expand import _sibling_metadata


@pytest.mark.parametrize("value", ["", None])
def test_multi_query_experiment_preserves_explicit_empty_labels(value: str | None) -> None:
    overrides = parse_model_query_overrides({"multi_query_ab_test_key": value, "multi_query_ab_variant": value})

    experiment = resolve_model_query_settings(overrides).multi_query.experiment

    assert experiment.key == value
    assert experiment.variant == value
    assert experiment.forced is False


@pytest.mark.parametrize("field", ["multi_query_ab_test_key", "multi_query_ab_variant"])
@pytest.mark.parametrize("value", [False, 0])
def test_multi_query_label_parser_exposes_invalid_internal_types(field: str, value) -> None:
    with pytest.raises(AttributeError):
        parse_model_query_overrides({field: value})


@pytest.mark.parametrize("field", ["top_k", "score_threshold"])
def test_profile_owner_exposes_invalid_required_numeric_values(field: str) -> None:
    parameters = {"profile": None, "top_k": 5, "score_threshold": 0.0}

    with pytest.raises(TypeError):
        apply_retrieval_profile_overrides(**{**parameters, field: None})


@pytest.mark.parametrize("field", ["retrieval_mode", "reranker_provider", "retrieval_contract_mode"])
@pytest.mark.parametrize("value", [0, False])
def test_profile_option_parser_exposes_supplied_non_text_values(field: str, value) -> None:
    with pytest.raises(AttributeError):
        apply_retrieval_profile_overrides(profile=None, top_k=5, score_threshold=0.0, **{field: value})


@pytest.mark.parametrize("anchor_id", ["", "anchor-1"])
def test_expansion_metadata_preserves_the_actual_anchor_identity(anchor_id: str) -> None:
    row = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        document_id=uuid4(),
        chunk_index=0,
        page_number=0,
        start_char=0,
        end_char=4,
        doc_metadata={},
        content="text",
    )

    neighbor = _neighbor_item(chunk=row, result={"score": 0.0}, anchor_chunk_id=anchor_id)
    sibling = _sibling_metadata(row=row, chunk_id=str(row.id), stored_meta={}, anchor_chunk_id=anchor_id)

    assert neighbor["metadata"]["neighbor_of"] == anchor_id
    assert neighbor["score"] == 0.0
    assert sibling["sibling_of"] == anchor_id
    assert sibling["start_char"] == 0


@pytest.mark.parametrize("resolver", [lexical_dataset_scope, LexicalDBMixin._lexical_dataset_scope])
def test_lexical_scope_returns_the_actual_empty_collection(resolver) -> None:
    assert resolver(None) == ([], None)


@pytest.mark.parametrize("resolver", [lexical_dataset_scope, LexicalDBMixin._lexical_dataset_scope])
def test_lexical_scope_keeps_all_requested_dataset_ids(resolver) -> None:
    first, second = uuid4(), uuid4()

    ids, first_text = resolver({"dataset_id": {"$in": [str(first), str(second)]}})

    assert ids == [first, second]
    assert first_text == str(first)
