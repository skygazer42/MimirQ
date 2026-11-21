import asyncio
import datetime as dt
from datetime import timezone

import pytest
from langchain_core.embeddings import Embeddings

if not hasattr(dt, "UTC"):
    dt.UTC = timezone.utc

import app.rag.embedding.adapter as adapter_module


class _DeterministicEmbeddingModel:
    def __init__(self) -> None:
        self.dimension = 3

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            size = float(len(text))
            checksum = float(sum(ord(ch) for ch in text) % 17)
            vectors.append([size, checksum, size + checksum + 1.0])
        return vectors


def test_langchain_embeddings_adapter_satisfies_embeddings_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter_module.settings, "EMBEDDING_CACHE_ENABLED", False, raising=False)
    adapter = adapter_module.LangChainEmbeddingsAdapter(_DeterministicEmbeddingModel(), normalize=False)

    assert isinstance(adapter, Embeddings)
    assert adapter.embed_documents(["ab", "xyz"]) == [[2.0, 8.0, 11.0], [3.0, 6.0, 10.0]]
    assert adapter.embed_query("ab") == [2.0, 8.0, 11.0]
    assert asyncio.run(adapter.aembed_documents(["ab"])) == [[2.0, 8.0, 11.0]]
    assert asyncio.run(adapter.aembed_query("xyz")) == [3.0, 6.0, 10.0]
