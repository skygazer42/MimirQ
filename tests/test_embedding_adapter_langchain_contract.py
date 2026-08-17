import asyncio
import datetime as dt
from datetime import timezone
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_community.vectorstores import faiss as faiss_module
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


def test_langchain_embeddings_adapter_works_through_faiss_from_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    class _IndexFlatL2:
        def __init__(self, dimension: int) -> None:
            self.dimension = dimension
            self.rows: list[list[float]] = []

        def add(self, matrix: Any) -> None:
            self.rows.extend(matrix.tolist())

    monkeypatch.setattr(adapter_module.settings, "EMBEDDING_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(
        faiss_module,
        "dependable_faiss_import",
        lambda: SimpleNamespace(
            IndexFlatL2=lambda dimension: _IndexFlatL2(dimension),
            normalize_L2=lambda _matrix: None,
        ),
        raising=True,
    )

    adapter = adapter_module.LangChainEmbeddingsAdapter(_DeterministicEmbeddingModel(), normalize=False)
    store = faiss_module.FAISS.from_texts(["alpha"], adapter, ids=["doc-1"])

    added_ids = store.add_texts(["beta"], ids=["doc-2"])

    assert added_ids == ["doc-2"]
    assert store.index.dimension == 3
    assert store.index.rows == [
        [5.0, 8.0, 14.0],
        [4.0, 4.0, 9.0],
    ]
    assert set(store.docstore._dict) == {"doc-1", "doc-2"}
