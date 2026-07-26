"""Dependency-free lexical embeddings for offline integration tests."""

import hashlib
import re
import unicodedata

from app.rag.embedding.base import BaseEmbeddingModel

_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)
_MODEL_NAME = "mimirq-deterministic-test-v1"


class DeterministicTestEmbedding(BaseEmbeddingModel):
    """Stable lexical hashing vectors; not intended for production retrieval quality."""

    def __init__(self, **kwargs):  # noqa: ANN003
        kwargs["model"] = str(kwargs.get("model") or _MODEL_NAME)
        kwargs["dimension"] = int(kwargs.get("dimension") or 256)
        super().__init__(**kwargs)
        if not 16 <= int(self.dimension or 0) <= 4096:
            raise ValueError("deterministic_test embedding dimension must be between 16 and 4096")

    def _add_feature(self, vector: list[float], feature: str, weight: float) -> None:
        digest = hashlib.blake2b(
            f"{_MODEL_NAME}:{feature}".encode("utf-8", "ignore"),
            digest_size=8,
        ).digest()
        bucket = int.from_bytes(digest[:4], "big") % len(vector)
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign * weight

    def _encode_one(self, text: str) -> list[float]:
        normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()[:4096]
        vector = [0.0] * int(self.dimension or 256)
        features = 0

        for token in _WORD_RE.findall(normalized):
            self._add_feature(vector, f"word:{token}", 2.0)
            features += 1

        compact = "".join(character for character in normalized if not character.isspace())
        for width, weight in ((2, 0.35), (3, 0.5)):
            for index in range(max(0, len(compact) - width + 1)):
                self._add_feature(vector, f"char:{width}:{compact[index:index + width]}", weight)
                features += 1

        if features == 0:
            self._add_feature(vector, "empty", 1.0)
        return vector

    def encode(self, message: str | list[str]) -> list[list[float]]:
        texts = [message] if isinstance(message, str) else list(message or [])
        return [self._encode_one(text) for text in texts]

    async def aencode(self, message: str | list[str]) -> list[list[float]]:
        return self.encode(message)
