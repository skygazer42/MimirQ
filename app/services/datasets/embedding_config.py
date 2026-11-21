"""Dataset-scoped embedding runtime configuration."""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.api.schemas.datasets import DatasetEmbeddingDefaults
from app.infrastructure.config import settings
from app.infrastructure.model_policy import EmbeddingProviders, reject_retired_provider
from app.rag.embedding.adapter import LangChainEmbeddingsAdapter, create_langchain_embeddings_from_config
from app.rag.embedding.utils import embedding_space_hash_for_config


@dataclass(frozen=True)
class DatasetEmbeddingRuntimeConfig:
    provider: str
    model: str
    api_base: str
    api_key: str
    embedding_space_hash: str
    collection_name: str
    dataset_scoped: bool


def collection_name_for_embedding_space(*, space_hash: str, dataset_scoped: bool) -> str:
    base = settings.MILVUS_COLLECTION_NAME.strip() or "documents"
    if not dataset_scoped:
        return base
    suffix = re.sub(r"\W+", "_", space_hash, flags=re.ASCII).strip("_")[:48] or "default"
    return f"{base}_emb_{suffix}"


def resolve_dataset_embedding_runtime(
    dataset_metadata: dict[str, Any] | None,
) -> DatasetEmbeddingRuntimeConfig:
    raw_defaults = dataset_metadata.get("embedding_defaults") if dataset_metadata is not None else None
    defaults = DatasetEmbeddingDefaults.model_validate({} if raw_defaults is None else raw_defaults)
    dataset_scoped = bool(defaults.model_dump(exclude_none=True))

    provider = (defaults.provider or settings.EMBEDDING_PROVIDER.strip() or "openai_compatible").lower()
    provider = EmbeddingProviders.PROVIDER_MAP.get(provider, provider)
    model = defaults.model or settings.EMBEDDING_MODEL.strip()
    api_base = defaults.api_base or settings.EMBEDDING_API_BASE.strip() or settings.LLM_API_BASE.strip()
    api_key = settings.EMBEDDING_API_KEY.strip() or settings.LLM_API_KEY.strip()
    reject_retired_provider(provider, capability="embedding")
    if dataset_scoped and settings.VECTOR_BACKEND != "milvus":
        raise ValueError("dataset-scoped embedding_defaults require VECTOR_BACKEND=milvus")

    space_hash = embedding_space_hash_for_config(
        provider=provider,
        model=model,
        base_url=api_base,
        length=16,
    )
    return DatasetEmbeddingRuntimeConfig(
        provider=provider,
        model=model,
        api_base=api_base,
        api_key=api_key,
        embedding_space_hash=space_hash,
        collection_name=collection_name_for_embedding_space(space_hash=space_hash, dataset_scoped=dataset_scoped),
        dataset_scoped=dataset_scoped,
    )


@lru_cache(maxsize=8)
def create_embeddings_for_runtime(runtime: DatasetEmbeddingRuntimeConfig) -> LangChainEmbeddingsAdapter:
    return create_langchain_embeddings_from_config(
        provider=runtime.provider,
        model=runtime.model,
        api_key=runtime.api_key,
        base_url=runtime.api_base,
        dimension=None,
        cache_space_hash=runtime.embedding_space_hash,
    )
