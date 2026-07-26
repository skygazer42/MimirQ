"""
Default embedding model configurations.

This module defines the supported embedding models with their configurations.
Models are identified by "provider/model_name" format.
"""
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_BGE_M3_NAME = "BAAI/bge-m3"
DETERMINISTIC_TEST_MODEL_ID = "deterministic_test/mimirq-deterministic-test-v1"
SILICONFLOW_EMBEDDINGS_URL = "https://api.siliconflow.cn/v1/embeddings"
OLLAMA_EMBEDDINGS_URL = "http://localhost:11434/api/embed"

# Environment variable names (not secrets themselves).
SILICONFLOW_ENV_VAR = "SILICONFLOW_API_KEY"
DASHSCOPE_ENV_VAR = "DASHSCOPE_API_KEY"
OPENAI_ENV_VAR = "OPENAI_API_KEY"
MODELSCOPE_ENV_VAR = "MODELSCOPE_ACCESS_TOKEN"


class EmbedModelInfo(BaseModel):
    """Embedding model configuration.

    Attributes:
        name: Model name (passed to API)
        dimension: Embedding vector dimension
        base_url: API endpoint URL
        api_key: API key or environment variable name
        model_id: Optional unique model identifier
    """

    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(..., description="Model name")
    dimension: int = Field(..., description="Vector dimension")
    base_url: str = Field(..., description="API base URL")
    api_key: str = Field(..., description="API Key or environment variable name")
    model_id: str | None = Field(None, description="Optional model ID")


# ============================================================
# Default embedding model configurations
# ============================================================

DEFAULT_EMBED_MODELS: dict[str, EmbedModelInfo] = {
    DETERMINISTIC_TEST_MODEL_ID: EmbedModelInfo(
        model_id=DETERMINISTIC_TEST_MODEL_ID,
        name="mimirq-deterministic-test-v1",
        dimension=256,
        base_url="offline://deterministic-test",
        api_key="no_api_key",
    ),
    # SiliconFlow - Chinese embedding provider
    "siliconflow/BAAI/bge-m3": EmbedModelInfo(
        model_id="siliconflow/BAAI/bge-m3",
        name=DEFAULT_BGE_M3_NAME,
        dimension=1024,
        base_url=SILICONFLOW_EMBEDDINGS_URL,
        api_key=SILICONFLOW_ENV_VAR,
    ),
    "siliconflow/Pro/BAAI/bge-m3": EmbedModelInfo(
        model_id="siliconflow/Pro/BAAI/bge-m3",
        name="Pro/BAAI/bge-m3",
        dimension=1024,
        base_url=SILICONFLOW_EMBEDDINGS_URL,
        api_key=SILICONFLOW_ENV_VAR,
    ),
    "siliconflow/Qwen/Qwen3-Embedding-0.6B": EmbedModelInfo(
        model_id="siliconflow/Qwen/Qwen3-Embedding-0.6B",
        name="Qwen/Qwen3-Embedding-0.6B",
        dimension=1024,
        base_url=SILICONFLOW_EMBEDDINGS_URL,
        api_key=SILICONFLOW_ENV_VAR,
    ),
    # Ollama - Local embedding models
    "ollama/nomic-embed-text": EmbedModelInfo(
        model_id="ollama/nomic-embed-text",
        name="nomic-embed-text",
        dimension=768,
        base_url=OLLAMA_EMBEDDINGS_URL,
        api_key="no_api_key",
    ),
    "ollama/bge-m3": EmbedModelInfo(
        model_id="ollama/bge-m3",
        name="bge-m3",
        dimension=1024,
        base_url=OLLAMA_EMBEDDINGS_URL,
        api_key="no_api_key",
    ),
    "ollama/mxbai-embed-large": EmbedModelInfo(
        model_id="ollama/mxbai-embed-large",
        name="mxbai-embed-large",
        dimension=1024,
        base_url=OLLAMA_EMBEDDINGS_URL,
        api_key="no_api_key",
    ),
    # vLLM - Local server with various models
    "vllm/Qwen/Qwen3-Embedding-0.6B": EmbedModelInfo(
        model_id="vllm/Qwen/Qwen3-Embedding-0.6B",
        name="Qwen3-Embedding-0.6B",
        dimension=1024,
        base_url="http://localhost:8000/v1/embeddings",
        api_key="no_api_key",
    ),
    "vllm/BAAI/bge-m3": EmbedModelInfo(
        model_id="vllm/BAAI/bge-m3",
        name=DEFAULT_BGE_M3_NAME,
        dimension=1024,
        base_url="http://localhost:8000/v1/embeddings",
        api_key="no_api_key",
    ),
    # DashScope (Alibaba Cloud)
    "dashscope/text-embedding-v4": EmbedModelInfo(
        model_id="dashscope/text-embedding-v4",
        name="text-embedding-v4",
        dimension=1024,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
        api_key=DASHSCOPE_ENV_VAR,
    ),
    # OpenAI
    "openai/text-embedding-3-small": EmbedModelInfo(
        model_id="openai/text-embedding-3-small",
        name="text-embedding-3-small",
        dimension=1536,
        base_url="https://api.openai.com/v1/embeddings",
        api_key=OPENAI_ENV_VAR,
    ),
    "openai/text-embedding-3-large": EmbedModelInfo(
        model_id="openai/text-embedding-3-large",
        name="text-embedding-3-large",
        dimension=3072,
        base_url="https://api.openai.com/v1/embeddings",
        api_key=OPENAI_ENV_VAR,
    ),
    # ModelScope (Alibaba)
    "modelscope/BAAI/bge-m3": EmbedModelInfo(
        model_id="modelscope/BAAI/bge-m3",
        name=DEFAULT_BGE_M3_NAME,
        dimension=1024,
        base_url="https://api-inference.modelscope.cn/v1/embeddings",
        api_key=MODELSCOPE_ENV_VAR,
    ),
    # Local sentence-transformers models
    "local/BAAI/bge-m3": EmbedModelInfo(
        model_id="local/BAAI/bge-m3",
        name=DEFAULT_BGE_M3_NAME,
        dimension=1024,
        base_url="local",
        api_key="no_api_key",
    ),
    "local/BAAI/bge-large-zh-v1.5": EmbedModelInfo(
        model_id="local/BAAI/bge-large-zh-v1.5",
        name="BAAI/bge-large-zh-v1.5",
        dimension=1024,
        base_url="local",
        api_key="no_api_key",
    ),
    "local/shibing624/text2vec-base-chinese": EmbedModelInfo(
        model_id="local/shibing624/text2vec-base-chinese",
        name="shibing624/text2vec-base-chinese",
        dimension=768,
        base_url="local",
        api_key="no_api_key",
    ),
}


def get_supported_model_ids() -> list[str]:
    """Get list of all supported model IDs.

    Returns:
        List of model_id strings in "provider/model" format
    """
    return list(DEFAULT_EMBED_MODELS.keys())


def get_model_info(model_id: str) -> EmbedModelInfo | None:
    """Get configuration for a specific model.

    Args:
        model_id: Model identifier in "provider/model" format

    Returns:
        EmbedModelInfo if found, None otherwise
    """
    return DEFAULT_EMBED_MODELS.get(model_id)


def get_models_by_provider(provider: str) -> dict[str, EmbedModelInfo]:
    """Get all models for a specific provider.

    Args:
        provider: Provider name (e.g., "siliconflow", "ollama")

    Returns:
        Dictionary of model_id to EmbedModelInfo
    """
    return {
        k: v
        for k, v in DEFAULT_EMBED_MODELS.items()
        if k.startswith(f"{provider}/")
    }
