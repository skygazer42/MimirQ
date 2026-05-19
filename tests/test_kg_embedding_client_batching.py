from __future__ import annotations

import asyncio


def test_kg_embedding_client_respects_kg_embed_batch_limit(monkeypatch) -> None:
    from app.core.config import settings
    import app.rag.llm.factory as llm_factory

    calls: list[list[str]] = []

    class FakeProvider:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            calls.append(list(texts))
            return [[float(len(text))] for text in texts]

    monkeypatch.setattr(llm_factory.milvus_store, "_init_embedding_model", lambda: FakeProvider(), raising=True)
    monkeypatch.setattr(settings, "EMBEDDING_API_BATCH_SIZE", 64, raising=False)
    monkeypatch.setattr(settings, "KG_EXTRACT_EMBED_BATCH_SIZE", 8, raising=False)

    client = llm_factory.EmbeddingClient()
    vectors = asyncio.run(client.generate_batch([f"text-{i}" for i in range(17)]))

    assert len(vectors) == 17
    assert [len(batch) for batch in calls] == [8, 8, 1]
