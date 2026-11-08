import pytest

from app.core.model_execution import RetiredModelProviderError
from app.rag.evaluation import ragas


@pytest.mark.parametrize("provider", ["local", " LOCAL "])
def test_ragas_rejects_retired_local_embeddings_before_building_clients(
    provider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ragas.settings, "EMBEDDING_PROVIDER", provider)

    def unexpected_clients():
        pytest.fail("A retired embedding provider must fail before allocating model clients")

    monkeypatch.setattr(ragas, "_build_http_clients", unexpected_clients)
    with pytest.raises(RetiredModelProviderError):
        ragas._build_llm_and_embeddings()
