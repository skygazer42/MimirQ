"""
SentenceTransformer local embedding model.

Supports local sentence-transformers models for embeddings.
"""
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.utils import logger


class SentenceTransformerEmbedding(BaseEmbeddingModel):
    """Local sentence-transformers embedding model.

    Uses sentence-transformers library for local embeddings.
    Supports models like:
    - BAAI/bge-m3
    - BAAI/bge-large-zh-v1.5
    - sentence-transformers/all-MiniLM-L6-v2

    Requires: pip install sentence-transformers torch
    """

    def __init__(self, **kwargs):
        """Initialize sentence-transformers embedding model.

        Args:
            model: Model name (e.g., "BAAI/bge-m3")
            dimension: Embedding vector dimension (auto-detected if None)
            base_url: Not used for local models
            api_key: Not used for local models
        """
        super().__init__(**kwargs)
        self._model = None
        self._device = self._get_device()

    def _get_device(self) -> str:
        """Detect available device for inference."""
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _load_model(self):
        """Lazy load the sentence-transformers model."""
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "sentence_transformers is required for local embeddings.\n"
                "Please install: pip install sentence-transformers torch"
            ) from e

        logger.info(
            f"Loading sentence-transformers model: {self.model} on {self._device}"
        )
        self._model = SentenceTransformer(self.model, device=self._device)

        # Auto-detect dimension if not set
        if self.dimension is None:
            self.dimension = self._model.get_sentence_embedding_dimension()

        return self._model

    def encode(self, message: str | list[str]) -> list[list[float]]:
        """Synchronously encode text(s) to embeddings."""
        if isinstance(message, str):
            message = [message]

        model = self._load_model()
        embeddings = model.encode(
            message,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        # Convert to list of lists
        if hasattr(embeddings, "tolist"):
            return embeddings.tolist()
        return [e.tolist() if hasattr(e, "tolist") else list(e) for e in embeddings]

    async def aencode(self, message: str | list[str]) -> list[list[float]]:
        """Asynchronously encode text(s) to embeddings.

        Note: sentence-transformers is synchronous, so we run it in a thread pool.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.encode, message)
