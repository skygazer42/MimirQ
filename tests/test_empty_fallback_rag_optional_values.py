from types import SimpleNamespace

import pytest

from app.rag.chunking.recommendations import decorate_chunk_strategy_note
from app.rag.core.metadata import ensure_hierarchy_overlay_metadata
from app.rag.embedding import factory
from app.rag.embedding.adapter import LangChainEmbeddingsAdapter, create_langchain_embeddings_from_config
from app.rag.embedding.matryoshka import resolve_matryoshka_dimension
from app.rag.engine_support.llm_routing import LlmRoutingMixin


@pytest.mark.parametrize("notes", [False, 0])
def test_optional_strategy_notes_reject_supplied_non_strings(notes):
    with pytest.raises((AttributeError, TypeError)):
        decorate_chunk_strategy_note("outline", notes)


def test_language_routing_exposes_an_invalid_required_detector_result(monkeypatch):
    monkeypatch.setattr(factory.settings, "EMBEDDING_LANGUAGE_ROUTING_ENABLED", True)
    monkeypatch.setattr(factory, "detect_language", lambda *args, **kwargs: SimpleNamespace(language=None))
    with pytest.raises((AttributeError, TypeError)):
        factory.resolve_language_aware_model_id(text="Document text", current_model_id="openai/base")


def test_metadata_overlay_preserves_supplied_falsy_identifiers():
    result = ensure_hierarchy_overlay_metadata(
        {"hierarchy_family_key": 0, "hierarchy_node_key": False}, document_id="doc-1", chunk_index=0
    )
    assert result["hierarchy_family_key"] == "0"
    assert result["hierarchy_node_key"] == "False"


@pytest.mark.parametrize("model", [False, 0])
def test_optional_route_alias_rejects_a_supplied_non_string(model):
    with pytest.raises((AttributeError, TypeError)):
        LlmRoutingMixin._is_route_model_compatible(route_model_name=model, default_model_name="openai/base")


@pytest.mark.parametrize("label", [False, 0])
def test_optional_dimension_label_rejects_a_supplied_non_string(label):
    with pytest.raises((AttributeError, TypeError)):
        resolve_matryoshka_dimension(query_complexity_label=label, source_dim=1024)


def test_embedding_adapter_preserves_a_real_optional_url_for_the_test_provider():
    adapter = create_langchain_embeddings_from_config(
        provider="deterministic_test", model="test", dimension=16, base_url=None, cache_space_hash="test-space"
    )
    assert isinstance(adapter, LangChainEmbeddingsAdapter)
