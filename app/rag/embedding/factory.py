"""
Embedding model factory and connectivity probes.

This module provides functions to:
- Select and instantiate embedding models by ID
- Probe embedding model connectivity
- List available models
"""

import asyncio
from typing import Literal, TypedDict

from app.infrastructure.config import settings
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.config import (
    DEFAULT_EMBED_MODELS,
    get_model_info,
    get_models_by_provider,
    get_supported_model_ids,
)
from app.rag.embedding.providers import (
    DashScopeEmbedding,
    DeterministicTestEmbedding,
    OllamaEmbedding,
    OpenAICompatibleEmbedding,
)
from app.rag.embedding.utils import logger
from app.rag.ingestion.governance.tagging.language import detect_language


class EmbeddingModelStatus(TypedDict):
    model_id: str
    status: Literal["available", "unavailable", "unsupported", "error"]
    message: str
    dimension: int | None


class EmbeddingModelStatusSummary(TypedDict):
    models: dict[str, EmbeddingModelStatus]
    total: int
    available: int


def select_embedding_model(model_id: str) -> BaseEmbeddingModel:
    """Select and instantiate an embedding model by ID.

    Args:
        model_id: Model identifier in "provider/model" format
                  (e.g., "siliconflow/BAAI/bge-m3", "ollama/nomic-embed-text")

    Returns:
        BaseEmbeddingModel instance

    Raises:
        ValueError: If model_id is not supported

    Examples:
        >>> model = select_embedding_model("ollama/nomic-embed-text")
        >>> embeddings = model.encode(["Hello world"])

        >>> async_model = select_embedding_model("siliconflow/BAAI/bge-m3")
        >>> embeddings = await async_model.aencode(["Hello world"])
    """
    from app.infrastructure.model_policy import reject_retired_provider

    provider = model_id.split("/", 1)[0]
    reject_retired_provider(provider, capability="embedding")
    model_info = get_model_info(model_id)
    if model_info is None:
        raise ValueError(f"Unsupported embed model: {model_id}. Supported models: {get_supported_model_ids()}")

    logger.info("Loading embedding model %s", model_id)

    # Convert to dict for instantiation
    config_dict = model_info.model_dump()

    if provider == "ollama":
        return OllamaEmbedding(**config_dict)
    if provider == "deterministic_test":
        return DeterministicTestEmbedding(**config_dict)
    if provider == "dashscope":
        return DashScopeEmbedding(**config_dict)
    return OpenAICompatibleEmbedding(**config_dict)


def resolve_language_aware_model_id(
    *,
    language: str | None = None,
    text: str | None = None,
    current_model_id: str | None = None,
) -> str:
    base_model_id = settings.EMBEDDING_MODEL if current_model_id is None else current_model_id
    base_model_id = base_model_id.strip()
    if not base_model_id:
        raise ValueError("Embedding model must be configured")
    if "/" not in base_model_id:
        base_model_id = f"openai/{base_model_id}"
    if not settings.EMBEDDING_LANGUAGE_ROUTING_ENABLED:
        return base_model_id

    lang = language.strip().lower() if language is not None else ""
    if not lang and text:
        lang = detect_language(text, min_chars=1).language.strip().lower()

    mapping = {
        "zh": settings.EMBEDDING_MODEL_ZH.strip(),
        "en": settings.EMBEDDING_MODEL_EN.strip(),
        "mixed": settings.EMBEDDING_MODEL_MIXED.strip(),
    }
    candidate = mapping.get(lang)
    if candidate and candidate in DEFAULT_EMBED_MODELS:
        return candidate
    return base_model_id


async def probe_embedding_model_status(model_id: str) -> EmbeddingModelStatus:
    """Probe connectivity and return the status of a specific embedding model.

    Args:
        model_id: Model identifier in "provider/model" format

    Returns:
        Dictionary containing status information:
        {
            "model_id": str,
            "status": "available" | "unavailable" | "unsupported",
            "message": str,
            "dimension": int | None
        }
    """
    try:
        if model_id not in DEFAULT_EMBED_MODELS:
            return {
                "model_id": model_id,
                "status": "unsupported",
                "message": f"Unsupported model: {model_id}",
                "dimension": None,
            }

        # Create model instance and test connection
        model = select_embedding_model(model_id)
        success, message = await model.test_connection()

        return {
            "model_id": model_id,
            "status": "available" if success else "unavailable",
            "message": message,
            "dimension": model.dimension,
        }

    except Exception as e:
        logger.warning("Failed to probe embedding model %s: %s", model_id, e)
        return {
            "model_id": model_id,
            "status": "error",
            "message": str(e),
            "dimension": None,
        }


async def probe_all_embedding_models_status() -> EmbeddingModelStatusSummary:
    """Probe all supported embedding models concurrently.

    Returns:
        Dictionary containing overall results:
        {
            "models": dict mapping model_id to status dict,
            "total": int,
            "available": int
        }
    """
    supported_models = get_supported_model_ids()
    # Each probe owns its error status; caller cancellation still propagates.
    model_statuses = await asyncio.gather(*(probe_embedding_model_status(model_id) for model_id in supported_models))
    results = {status["model_id"]: status for status in model_statuses}

    available_count = sum(status["status"] == "available" for status in results.values())

    return {
        "models": results,
        "total": len(supported_models),
        "available": available_count,
    }


def get_default_embedding_model_id() -> str:
    """Get the default embedding model ID."""
    return "siliconflow/BAAI/bge-m3"


def list_embedding_providers() -> list[str]:
    """List all embedding providers."""
    providers = set()
    for model_id in DEFAULT_EMBED_MODELS:
        if "/" in model_id:
            provider = model_id.split("/", 1)[0]
            providers.add(provider)
    return sorted(providers)


def list_models_by_provider(provider: str) -> list[str]:
    """List all model IDs for a specific provider."""
    return list(get_models_by_provider(provider))
