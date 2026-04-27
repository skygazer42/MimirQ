from __future__ import annotations


def test_embedding_provider_wrappers_subclass_openai_compatible() -> None:
    from app.rag.embedding.providers.bedrock import BedrockEmbedding
    from app.rag.embedding.providers.cohere import CohereEmbedding
    from app.rag.embedding.providers.jina import JinaEmbedding
    from app.rag.embedding.providers.openai import OpenAICompatibleEmbedding
    from app.rag.embedding.providers.voyage import VoyageEmbedding

    assert issubclass(VoyageEmbedding, OpenAICompatibleEmbedding)
    assert issubclass(CohereEmbedding, OpenAICompatibleEmbedding)
    assert issubclass(JinaEmbedding, OpenAICompatibleEmbedding)
    assert issubclass(BedrockEmbedding, OpenAICompatibleEmbedding)
