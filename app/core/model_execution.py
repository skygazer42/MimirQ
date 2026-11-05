"""The API's retired in-process model selections, shared by request and runtime boundaries."""

from typing import Literal

ModelCapability = Literal["embedding", "reranker", "keyword", "sparse", "colbert", "kg_extraction"]

_RETIRED_PROVIDERS = {
    "embedding": frozenset({"local"}),
    "reranker": frozenset(
        {
            "cross_encoder",
            "crossencoder",
            "sentence_transformers",
            "sentence_transformer",
            "local_bge_v2_m3",
            "bge_v2_m3",
        }
    ),
    "keyword": frozenset({"hanlp"}),
    "sparse": frozenset({"splade"}),
    "colbert": frozenset({"hf"}),
    "kg_extraction": frozenset({"gliner", "hybrid"}),
}


class RetiredModelProviderError(ValueError):
    """A saved or requested provider requires model execution that has been removed."""


def reject_retired_model_provider(provider: str | None, *, capability: ModelCapability) -> None:
    normalized = (provider or "").strip().lower().replace("-", "_")
    if normalized in _RETIRED_PROVIDERS[capability]:
        raise RetiredModelProviderError(
            f"{capability} provider {provider!r} has been retired from the API. Select a supported provider explicitly."
        )


def reject_retired_retrieval_profile(profile: str | None) -> None:
    if (profile or "").strip().lower() == "sparse_splade":
        raise RetiredModelProviderError("The sparse_splade retrieval profile has been retired")


def validate_rag_execution_selection(
    *, reranker_provider: str | None = None, sparse_provider: str | None = None, retrieval_profile: str | None = None
) -> None:
    reject_retired_model_provider(reranker_provider, capability="reranker")
    reject_retired_model_provider(sparse_provider, capability="sparse")
    reject_retired_retrieval_profile(retrieval_profile)
