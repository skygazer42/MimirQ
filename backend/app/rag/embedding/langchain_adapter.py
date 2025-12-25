"""
LangChain-compatible embeddings adapter.

Adapts app.rag.embedding models to LangChain's Embeddings interface
for use with LangChain vector stores (Milvus, FAISS, Chroma, etc.).
"""
from typing import List

from app.rag.embedding.base import BaseEmbeddingModel
from app.kg.utils import get_logger

logger = get_logger("rag.embedding.langchain")


class LangChainEmbeddingsAdapter:
    """LangChain Embeddings interface adapter.

    Adapts any BaseEmbeddingModel to LangChain's expected interface:
    - embed_documents(texts: List[str]) -> List[List[float]]
    - embed_query(text: str) -> List[float]

    Usage:
        from app.rag.embedding import select_embedding_model
        from app.rag.embedding.langchain_adapter import LangChainEmbeddingsAdapter

        model = select_embedding_model("ollama/nomic-embed-text")
        embeddings = LangChainEmbeddingsAdapter(model)

        # Use with LangChain vector stores
        from langchain_community.vectorstores import Milvus
        vectorstore = Milvus(embedding_function=embeddings, ...)
    """

    def __init__(self, model: BaseEmbeddingModel, normalize: bool = True):
        """Initialize the adapter.

        Args:
            model: BaseEmbeddingModel instance
            normalize: Whether to normalize embeddings (default: True)
        """
        self._model = model
        self._normalize = normalize
        self._dimension = model.dimension

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of text documents.

        Args:
            texts: List of text strings

        Returns:
            List of embedding vectors
        """
        embeddings = self._model.encode(texts)

        if self._normalize:
            embeddings = self._normalize_vectors(embeddings)

        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query text.

        Args:
            text: Query text string

        Returns:
            Embedding vector
        """
        embeddings = self._model.encode([text])

        if self._normalize:
            embeddings = self._normalize_vectors(embeddings)

        return embeddings[0]

    def _normalize_vectors(self, vectors: List[List[float]]) -> List[List[float]]:
        """Normalize embeddings to unit length.

        Args:
            vectors: List of embedding vectors

        Returns:
            Normalized vectors
        """
        import numpy as np

        array = np.array(vectors, dtype=float)
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (array / norms).tolist()

    @property
    def dimension(self) -> int:
        """Get the embedding dimension."""
        return self._dimension


def create_langchain_embeddings(
    model_id: str, normalize: bool = True
) -> LangChainEmbeddingsAdapter:
    """Create a LangChain-compatible embeddings instance.

    Convenience function to create embeddings adapter from model_id.

    Args:
        model_id: Model identifier (e.g., "ollama/nomic-embed-text")
        normalize: Whether to normalize embeddings

    Returns:
        LangChainEmbeddingsAdapter instance

    Examples:
        from app.rag.embedding.langchain_adapter import create_langchain_embeddings

        embeddings = create_langchain_embeddings("ollama/nomic-embed-text")
        vectors = embeddings.embed_documents(["Hello", "World"])
    """
    from app.rag.embedding import select_embedding_model

    model = select_embedding_model(model_id)
    return LangChainEmbeddingsAdapter(model, normalize=normalize)


def create_langchain_embeddings_from_config(
    provider: str, model: str, api_key: str = "", base_url: str = "", dimension: int = None
) -> LangChainEmbeddingsAdapter:
    """Create LangChain embeddings from config (for compatibility with milvus.py).

    This function provides backward compatibility with the old embedding setup
    in app/storage/vector/milvus.py.

    Args:
        provider: Provider name (e.g., "local", "openai_compatible", "dashscope")
        model: Model name
        api_key: API key (optional)
        base_url: API base URL (optional)
        dimension: Embedding dimension (optional)

    Returns:
        LangChainEmbeddingsAdapter instance
    """
    from app.rag.embedding.sentence_transformer import SentenceTransformerEmbedding
    from app.rag.embedding.openai_compatible import OpenAICompatibleEmbedding
    from app.rag.embedding.dashscope import DashScopeEmbedding

    provider = provider.lower()

    if provider == "local":
        embedding_model = SentenceTransformerEmbedding(
            model=model, dimension=dimension, base_url=base_url, api_key=api_key
        )
    elif provider == "dashscope":
        embedding_model = DashScopeEmbedding(
            model=model, dimension=dimension, base_url=base_url, api_key=api_key
        )
    else:  # openai_compatible, openai, etc.
        embedding_model = OpenAICompatibleEmbedding(
            model=model, dimension=dimension, base_url=base_url, api_key=api_key
        )

    return LangChainEmbeddingsAdapter(embedding_model, normalize=True)
