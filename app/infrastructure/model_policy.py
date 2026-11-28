"""Model provider selection policy shared by request and runtime boundaries."""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PostRerankStageConfig(BaseModel):
    """A validated post-rerank stage; zero top_n inherits the current candidate limit."""

    model_config = ConfigDict(str_strip_whitespace=True, str_to_lower=True, extra="ignore", frozen=True)

    provider: str = Field(min_length=1)
    top_n: int = Field(default=0, ge=0)


class EmbeddingProviders:
    """Embedding provider constants."""

    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    DASHSCOPE = "dashscope"
    OLLAMA = "ollama"
    DETERMINISTIC_TEST = "deterministic_test"

    # Provider map (alias -> canonical name)
    PROVIDER_MAP = {
        OPENAI: OPENAI_COMPATIBLE,
        OPENAI_COMPATIBLE: OPENAI_COMPATIBLE,
        DASHSCOPE: DASHSCOPE,
        OLLAMA: OLLAMA,
        DETERMINISTIC_TEST: DETERMINISTIC_TEST,
    }
    ALL: frozenset[str] = frozenset(PROVIDER_MAP)


ModelCapability = Literal["embedding", "reranker", "keyword", "sparse", "kg_extraction", "parser"]

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
            "colbert",
            "late_interaction",
        }
    ),
    "keyword": frozenset({"hanlp"}),
    "sparse": frozenset({"det", "deterministic", "splade"}),
    "kg_extraction": frozenset({"gliner", "hybrid"}),
    "parser": frozenset({"tcadp", "tcadp_parser", "colpali", "col_pali", "colqwen", "col_qwen", "audio", "video"}),
}


class RetiredModelProviderError(ValueError):
    """A saved or requested provider has been retired from the API."""


def reject_retired_provider(provider: str | None, *, capability: ModelCapability) -> None:
    if provider is None:
        return
    normalized = provider.strip().lower().replace("-", "_")
    if capability == "parser":
        normalized = normalized.replace(" ", "_")
    if normalized in _RETIRED_PROVIDERS[capability]:
        raise RetiredModelProviderError(
            f"{capability} provider {provider!r} has been retired from the API. Select a supported provider explicitly."
        )


def reject_retired_retrieval_profile(profile: str | None) -> None:
    if profile is None:
        return
    if profile.strip().lower() == "sparse_splade":
        raise RetiredModelProviderError("The sparse_splade retrieval profile has been retired")


def reject_retired_retrieval_options(options: Mapping[str, Any]) -> None:
    retired = {
        "sparse_retrieval_enabled",
        "sparse_retrieval_provider",
        "sparse_enabled",
        "sparse_provider",
    }.intersection(options)
    if retired:
        raise RetiredModelProviderError(
            "Sparse retrieval has been retired. Remove these options: " + ", ".join(sorted(retired))
        )
    for name in ("fusion_budgets", "fusion_min_scores", "fusion_weights"):
        channels = options.get(name)
        if isinstance(channels, Mapping) and any(
            isinstance(channel, str) and channel.strip().lower() == "sparse" for channel in channels
        ):
            raise RetiredModelProviderError("Sparse retrieval has been retired. Remove sparse from " + name)


def validate_rag_execution_selection(
    *, reranker_provider: str | None = None, retrieval_profile: str | None = None
) -> None:
    reject_retired_provider(reranker_provider, capability="reranker")
    reject_retired_retrieval_profile(retrieval_profile)
