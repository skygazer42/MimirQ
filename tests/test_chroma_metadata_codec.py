from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.storage.vector.factory as factory_module


def test_chroma_metadata_codec_round_trips_complex_values() -> None:
    raw = {
        "title": "release notes",
        "stats": {"headings_changed": 1, "nested": {"ok": True}},
        "tags": ["release", "backend"],
        "empty": [],
        "reserved_looking": "__mimirq_json_v1__:{\"not\":\"encoded\"}",
    }

    encoded = factory_module._encode_chroma_metadata(raw)

    assert all(value is None or isinstance(value, (str, int, float, bool)) for value in encoded.values())
    assert factory_module._decode_chroma_metadata(encoded) == raw


def test_chroma_vector_store_encodes_writes_and_decodes_search_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_metadata: list[dict[str, object]] = []

    class _FakeChroma:
        def __init__(self, **_kwargs) -> None:
            self._collection = SimpleNamespace(delete=lambda **_kwargs: None)

        def add_texts(self, *, texts, metadatas, ids) -> None:  # noqa: ANN001
            del texts, ids
            captured_metadata.extend(metadatas)

        def similarity_search_with_score(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return [
                (
                    SimpleNamespace(
                        id="chunk-1",
                        page_content="release token",
                        metadata=captured_metadata[0],
                    ),
                    0.0,
                )
            ]

    monkeypatch.setattr(factory_module, "_get_chroma_cls", lambda: _FakeChroma, raising=True)
    monkeypatch.setattr(
        factory_module,
        "create_langchain_embeddings_from_config",
        lambda **_kwargs: object(),
        raising=True,
    )
    monkeypatch.setattr(factory_module.settings, "CHROMA_PERSIST_PATH", "", raising=False)

    store = factory_module.ChromaVectorStore()
    document_id = uuid4()
    tenant_id = uuid4()
    ids = store.add_documents(
        [
            {
                "content": "release token",
                "metadata": {
                    "chunk_id": "chunk-1",
                    "transform_stats": {"headings_changed": 0},
                    "tags": ["release", "smoke"],
                },
            }
        ],
        document_id,
        tenant_id,
    )

    assert ids == ["chunk-1"]
    assert isinstance(captured_metadata[0]["transform_stats"], str)
    assert isinstance(captured_metadata[0]["tags"], str)

    results = store.search(
        "release",
        top_k=1,
        score_threshold=0.0,
        document_ids=[document_id],
        tenant_id=tenant_id,
        metadata_filter={"transform_stats.headings_changed": 0},
    )

    assert len(results) == 1
    assert results[0]["metadata"]["transform_stats"] == {"headings_changed": 0}
    assert results[0]["metadata"]["tags"] == ["release", "smoke"]
