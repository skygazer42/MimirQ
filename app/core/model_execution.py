"""Retired provider selections shared by request and runtime boundaries."""

import json
from typing import Literal

ModelCapability = Literal["embedding", "reranker", "keyword", "sparse", "colbert", "kg_extraction", "parser"]

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
            "ltr",
            "xgboost_ltr",
        }
    ),
    "keyword": frozenset({"hanlp"}),
    "sparse": frozenset({"splade"}),
    "colbert": frozenset({"hf"}),
    "kg_extraction": frozenset({"gliner", "hybrid"}),
    "parser": frozenset({"tcadp", "tcadp_parser"}),
}


class RetiredModelProviderError(ValueError):
    """A saved or requested provider has been retired from the API."""


def reject_retired_provider(provider: str | None, *, capability: ModelCapability) -> None:
    normalized = (provider if provider is not None else "").strip().lower().replace("-", "_")
    if capability == "parser":
        normalized = normalized.replace(" ", "_")
    if normalized in _RETIRED_PROVIDERS[capability]:
        raise RetiredModelProviderError(
            f"{capability} provider {provider!r} has been retired from the API. Select a supported provider explicitly."
        )


def reject_retired_retrieval_profile(profile: str | None) -> None:
    if (profile if profile is not None else "").strip().lower() == "sparse_splade":
        raise RetiredModelProviderError("The sparse_splade retrieval profile has been retired")


def reject_retired_rerank_providers(raw: str | None) -> None:
    if not raw:
        return
    try:
        stages = json.loads(raw)
    except json.JSONDecodeError:
        return
    if isinstance(stages, list):
        for stage in stages:
            if isinstance(stage, dict):
                reject_retired_provider(str(stage.get("provider") or ""), capability="reranker")


def validate_rag_execution_selection(
    *, reranker_provider: str | None = None, sparse_provider: str | None = None, retrieval_profile: str | None = None
) -> None:
    reject_retired_provider(reranker_provider, capability="reranker")
    reject_retired_provider(sparse_provider, capability="sparse")
    reject_retired_retrieval_profile(retrieval_profile)
