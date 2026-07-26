import math

import pytest

from app.core.constants import EmbeddingProviders
from app.rag.embedding import create_langchain_embeddings_from_config
from app.rag.embedding.factory import select_embedding_model
from app.rag.embedding.providers.deterministic_test import DeterministicTestEmbedding


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    return numerator / denominator if denominator else 0.0


def test_deterministic_test_embedding_is_stable_and_lexical() -> None:
    model = DeterministicTestEmbedding(dimension=128)
    document = model.encode("Release token LIVE-CLOSED-LOOP-AXIOM-2049")[0]
    repeated = model.encode("Release token LIVE-CLOSED-LOOP-AXIOM-2049")[0]
    related = model.encode("return the release token from the document")[0]
    unrelated = model.encode("quarterly rainfall and ocean temperature")[0]

    assert document == repeated
    assert len(document) == 128
    assert _cosine(document, related) > _cosine(document, unrelated)


@pytest.mark.asyncio
async def test_deterministic_test_provider_factory_is_offline_and_normalized() -> None:
    embeddings = create_langchain_embeddings_from_config(
        provider="deterministic_test",
        model="mimirq-deterministic-test-v1",
        dimension=64,
    )

    sync_vector = embeddings.embed_query("shared lexical token")
    async_vector = (await embeddings._model.aencode("shared lexical token"))[0]

    assert EmbeddingProviders.PROVIDER_MAP["deterministic_test"] == "deterministic_test"
    assert len(sync_vector) == 64
    assert math.isclose(math.sqrt(sum(value * value for value in sync_vector)), 1.0)
    assert any(async_vector)


def test_deterministic_test_select_embedding_model_supports_legacy_factory() -> None:
    model = select_embedding_model("deterministic_test/mimirq-deterministic-test-v1")

    assert isinstance(model, DeterministicTestEmbedding)
    assert model.dimension == 256
