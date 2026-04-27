from __future__ import annotations

import json


def test_get_vector_store_routes_qdrant_backend(monkeypatch) -> None:  # noqa: ANN001
    import app.storage.vector.factory as factory

    monkeypatch.setattr(factory.settings, "VECTOR_BACKEND", "qdrant", raising=False)
    factory._VECTOR_STORE_SINGLETONS.clear()

    store = factory.get_vector_store()
    assert store.__class__.__name__ == "QdrantVectorStore"


def test_get_vector_store_routes_pgvector_backend(monkeypatch) -> None:  # noqa: ANN001
    import app.storage.vector.factory as factory

    monkeypatch.setattr(factory.settings, "VECTOR_BACKEND", "pgvector", raising=False)
    factory._VECTOR_STORE_SINGLETONS.clear()

    store = factory.get_vector_store()
    assert store.__class__.__name__ == "PGVectorStore"


def test_get_vector_store_routes_backend_by_region(monkeypatch) -> None:  # noqa: ANN001
    import app.storage.vector.factory as factory

    monkeypatch.setattr(factory.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(factory.settings, "DATA_REGION", "cn-shanghai", raising=False)
    monkeypatch.setattr(
        factory.settings,
        "VECTOR_REGION_BACKENDS",
        json.dumps({"cn-shanghai": "qdrant", "eu-west-1": "pgvector"}),
        raising=False,
    )
    factory._VECTOR_STORE_SINGLETONS.clear()

    cn_store = factory.get_vector_store()
    eu_store = factory.get_vector_store(region="eu-west-1")
    default_store = factory.get_vector_store(region="us-east-1")

    assert cn_store.__class__.__name__ == "QdrantVectorStore"
    assert eu_store.__class__.__name__ == "PGVectorStore"
    assert default_store.__class__.__name__ == "MilvusVectorStore"
