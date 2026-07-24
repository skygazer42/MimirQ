"""Dataset-scoped embedding runtime configuration."""


import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.core.constants import EmbeddingProviders
from app.rag.embedding import create_langchain_embeddings_from_config
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


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _safe_collection_suffix(value: str) -> str:
    suffix = re.sub(r"\W+", "_", value, flags=re.ASCII).strip("_")
    return suffix[:48] or "default"


def _base_embedding_config() -> tuple[str, str, str, str]:
    provider_raw = _clean(getattr(settings, "EMBEDDING_PROVIDER", "")) or "openai_compatible"
    provider = EmbeddingProviders.PROVIDER_MAP.get(provider_raw.lower(), provider_raw.lower())
    model = _clean(getattr(settings, "EMBEDDING_MODEL", ""))
    api_base = _clean(getattr(settings, "EMBEDDING_API_BASE", "")) or _clean(getattr(settings, "LLM_API_BASE", ""))
    api_key = _clean(getattr(settings, "EMBEDDING_API_KEY", "")) or _clean(getattr(settings, "LLM_API_KEY", ""))
    return provider, model, api_base, api_key


def _vector_backend() -> str:
    return _clean(getattr(settings, "VECTOR_BACKEND", "milvus")).lower() or "milvus"


def collection_name_for_embedding_space(*, space_hash: str, dataset_scoped: bool) -> str:
    base = _clean(getattr(settings, "MILVUS_COLLECTION_NAME", "")) or "documents"
    if not dataset_scoped:
        return base
    return f"{base}_emb_{_safe_collection_suffix(space_hash)}"


def resolve_dataset_embedding_runtime(
    dataset_metadata: dict[str, Any] | None,
) -> DatasetEmbeddingRuntimeConfig:
    provider, model, api_base, api_key = _base_embedding_config()

    raw = dataset_metadata.get("embedding_defaults") if isinstance(dataset_metadata, dict) else None
    dataset_scoped = isinstance(raw, dict) and any(_clean(raw.get(key)) for key in ("provider", "model", "api_base"))
    if isinstance(raw, dict):
        provider = EmbeddingProviders.PROVIDER_MAP.get(_clean(raw.get("provider")).lower(), _clean(raw.get("provider")).lower()) or provider
        model = _clean(raw.get("model")) or model
        api_base = _clean(raw.get("api_base")) or api_base
    if dataset_scoped and _vector_backend() != "milvus":
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
        collection_name=collection_name_for_embedding_space(
            space_hash=space_hash,
            dataset_scoped=dataset_scoped,
        ),
        dataset_scoped=dataset_scoped,
    )


@lru_cache(maxsize=8)
def create_embeddings_for_runtime(runtime: DatasetEmbeddingRuntimeConfig):
    return create_langchain_embeddings_from_config(
        provider=runtime.provider,
        model=runtime.model,
        api_key=runtime.api_key,
        base_url=runtime.api_base,
        dimension=None,
        cache_space_hash=runtime.embedding_space_hash,
    )
