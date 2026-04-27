"""
Embedding model factory and testing utilities.

This module provides functions to:
- Select and instantiate embedding models by ID
- Test embedding model connectivity
- List available models
"""
import asyncio

from app.core.config import settings
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.config import (
    DEFAULT_EMBED_MODELS,
    get_model_info,
    get_supported_model_ids,
)
from app.rag.embedding.providers import (
    DashScopeEmbedding,
    OllamaEmbedding,
    OpenAICompatibleEmbedding,
    SentenceTransformerEmbedding,
)
from app.rag.embedding.utils import logger
from app.rag.preprocessing.language import detect_language


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
    supported_models = get_supported_model_ids()

    if model_id not in supported_models:
        raise ValueError(
            f"Unsupported embed model: {model_id}. "
            f"Supported models: {supported_models}"
        )

    model_info = get_model_info(model_id)
    if model_info is None:
        raise ValueError(f"Model configuration not found: {model_id}")

    logger.info(f"Loading embedding model {model_id}")

    # Parse provider from model_id (format: "provider/model")
    provider = model_id.split("/", 1)[0] if "/" in model_id else ""

    # Convert to dict for instantiation
    config_dict = model_info.model_dump()

    if provider == "ollama":
        return OllamaEmbedding(**config_dict)
    elif provider == "local":
        return SentenceTransformerEmbedding(**config_dict)
    elif provider == "dashscope":
        return DashScopeEmbedding(**config_dict)
    else:
        # All other providers use OpenAI-compatible format
        return OpenAICompatibleEmbedding(**config_dict)


def resolve_language_aware_model_id(
    *,
    language: str | None = None,
    text: str | None = None,
    current_model_id: str | None = None,
) -> str:
    base_model_id = str(current_model_id or settings.EMBEDDING_MODEL or "text-embedding-3-small").strip()
    if "/" not in base_model_id:
        base_model_id = f"openai/{base_model_id}"
    if not bool(getattr(settings, "EMBEDDING_LANGUAGE_ROUTING_ENABLED", False)):
        return base_model_id

    lang = str(language or "").strip().lower()
    if not lang and text:
        try:
            lang = str(detect_language(str(text or ""), min_chars=1).language or "").strip().lower()
        except Exception:
            lang = ""

    mapping = {
        "zh": str(getattr(settings, "EMBEDDING_MODEL_ZH", "") or "").strip(),
        "en": str(getattr(settings, "EMBEDDING_MODEL_EN", "") or "").strip(),
        "mixed": str(getattr(settings, "EMBEDDING_MODEL_MIXED", "") or "").strip(),
    }
    candidate = mapping.get(lang, "")
    if candidate and candidate in get_supported_model_ids():
        return candidate
    return base_model_id


async def test_embedding_model_status(model_id: str) -> dict:
    """Test the status of a specific embedding model.

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
        supported_models = get_supported_model_ids()

        if model_id not in supported_models:
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
        logger.warning(f"Failed to test embedding model status {model_id}: {e}")
        return {
            "model_id": model_id,
            "status": "error",
            "message": str(e),
            "dimension": None,
        }


async def test_all_embedding_models_status() -> dict:
    """Test all supported embedding models concurrently.

    Returns:
        Dictionary containing overall results:
        {
            "models": dict mapping model_id to status dict,
            "total": int,
            "available": int
        }
    """
    supported_models = get_supported_model_ids()
    results = {}

    # Test all models concurrently
    tasks = [test_embedding_model_status(model_id) for model_id in supported_models]
    model_statuses = await asyncio.gather(*tasks, return_exceptions=True)

    for i, status in enumerate(model_statuses):
        if isinstance(status, Exception):
            model_id = supported_models[i]
            results[model_id] = {
                "model_id": model_id,
                "status": "error",
                "message": str(status),
                "dimension": None,
            }
        else:
            results[status["model_id"]] = status

    available_count = len(
        [m for m in results.values() if m.get("status") == "available"]
    )

    return {
        "models": results,
        "total": len(supported_models),
        "available": available_count,
    }


def get_default_embedding_model() -> str:
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
    return [
        model_id
        for model_id in DEFAULT_EMBED_MODELS
        if model_id.startswith(f"{provider}/")
    ]
