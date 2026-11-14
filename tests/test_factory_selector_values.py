import pytest

from app.rag.reranker import factory
from app.rag.reranker.long_context_rerank import LongContextReranker
from app.storage.vector import factory as vector_factory


@pytest.mark.parametrize("provider", ["dashscope", "openai"])
def test_api_reranker_preserves_explicit_empty_configuration(provider, monkeypatch) -> None:
    monkeypatch.setattr(factory.settings, "RERANKER_MODEL", "configured-model")
    monkeypatch.setattr(factory.settings, "RERANKER_API_KEY", "configured-key")
    monkeypatch.setattr(factory.settings, "LLM_API_KEY", "llm-key")
    monkeypatch.setattr(factory.settings, "RERANKER_API_BASE", "https://configured.invalid")
    monkeypatch.setattr(factory, "_api_reranker_cache", {})
    result = factory.get_reranker(provider, model_name="", api_key="", base_url="", timeout=0)
    assert result.model == ""
    assert result.api_key == ""
    assert result.url == ""
    assert result.timeout.total == 0


def test_mmr_factory_preserves_zero_diversity_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "RETRIEVAL_MMR_LAMBDA", 0.7)
    monkeypatch.setattr(factory, "_local_reranker_cache", {})
    assert factory.get_reranker("mmr", lambda_mult=0).lambda_mult == 0


def test_long_context_constructor_owns_the_label_and_cache_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "_local_reranker_cache", {})
    default = factory.get_reranker("long_context")
    assert default is factory.get_reranker("long_context", model_name=LongContextReranker().model_name)
    assert factory.get_reranker("long_context", model_name="").model_name == ""


def test_legacy_reranker_factory_forwards_a_selected_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    selected = object()

    def resolve(provider):
        seen.append(provider)
        return selected

    monkeypatch.setattr(factory, "get_reranker", resolve)
    with pytest.warns(DeprecationWarning):
        assert factory.get_rag_reranker("weighted") is selected
    assert seen == ["weighted"]


@pytest.mark.parametrize("value", [0, False, [], {}])
def test_vector_factory_exposes_bad_selector_types(value, monkeypatch) -> None:
    monkeypatch.setattr(vector_factory.settings, "DATA_REGION", "configured")
    with pytest.raises(AttributeError):
        vector_factory._normalize_region(value)
    with pytest.raises(AttributeError):
        vector_factory._resolve_vector_backend(backend=value)
