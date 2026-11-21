import pytest

from app.infrastructure.model_policy import RetiredModelProviderError
from app.rag.evaluation.regression import ragas


@pytest.mark.parametrize("provider", ["local", " LOCAL "])
def test_ragas_rejects_retired_local_before_building_embedding_models(
    provider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ragas.settings, "EMBEDDING_PROVIDER", provider)

    def unexpected_clients(**_kwargs):
        pytest.fail("A retired embedding provider must fail before allocating model clients")

    monkeypatch.setattr(ragas, "ChatOpenAI", lambda **_kwargs: object())
    monkeypatch.setattr(ragas, "create_langchain_embeddings_from_config", unexpected_clients)
    monkeypatch.setattr(ragas, "OpenAIEmbeddings", unexpected_clients)
    with pytest.raises(RetiredModelProviderError):
        ragas._build_llm_and_embeddings(http_client=object(), http_async_client=object())
