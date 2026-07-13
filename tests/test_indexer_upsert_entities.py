
import uuid
from uuid import UUID

import pytest

from app.query.normalize import normalize_query


def test_indexer_upsert_entities_sets_extra_data_and_indexes_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.indexer as indexer_mod

    class _StubMilvus:  # noqa: D401
        """No-op vector adapter."""

        def add_vectors(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            return []

    monkeypatch.setattr(indexer_mod, "get_milvus_adapter", lambda **_k: _StubMilvus(), raising=True)

    class _FakeSession:
        def commit(self) -> None:  # noqa: D401
            """No-op."""

        def flush(self) -> None:  # noqa: D401
            """No-op."""

    class _FakeEntity:
        def __init__(self) -> None:
            self.id = uuid.uuid4()
            self.vector = None
            self.extra_data = None
            self.description = None

    db = _FakeSession()
    indexer = indexer_mod.Indexer(db)  # type: ignore[arg-type]

    ent = _FakeEntity()

    def _fake_get_or_create_entity(self, **_kwargs):  # noqa: ANN001, ANN003
        return ent

    monkeypatch.setattr(indexer_mod.Indexer, "_get_or_create_entity", _fake_get_or_create_entity, raising=True)

    called = {"indexed": False}

    def _fake_index_entity_vectors(self, entities):  # noqa: ANN001
        called["indexed"] = True
        assert entities and entities[0] is ent
        return []

    monkeypatch.setattr(indexer_mod.Indexer, "_index_entity_vectors", _fake_index_entity_vectors, raising=True)

    out = indexer.upsert_entities(
        tenant_id=UUID(int=1),
        entities=[
            {
                "name": "Setup Python venv",
                "normalized_name": "setup python venv",
                "type": "Skill",
                "description": "Create and activate a venv.",
                "vector": [0.1],
                "extra_data": {"steps": ["python -m venv .venv"]},
            }
        ],
        commit=True,
        options=None,
    )

    assert out == [ent]
    assert ent.vector == [0.1]
    assert ent.extra_data == {"steps": ["python -m venv .venv"]}
    assert called["indexed"] is True


def test_index_text_uses_query_normalization_and_preserves_display_content() -> None:
    import app.services.indexer as indexer_mod

    raw = " ＡＢＣ。 V1.2 １，０００ mb C:\\Docs "
    expected = "abc. 1.2 1000 MB c:/docs"

    assert normalize_query(raw).normalized_text == expected
    index_text, metadata = indexer_mod._chunk_index_content(raw, {})

    assert index_text == expected
    assert metadata["_retrieval_text"] == expected
    assert metadata["_retrieval_display_content"] == raw


def test_index_text_injects_existing_metadata_without_changing_chunk_body() -> None:
    import app.services.indexer as indexer_mod

    body = "Install the package."
    index_text, metadata = indexer_mod._chunk_index_content(
        body,
        {
            "document_title": "MimirQ Guide",
            "header_path": ["Setup", "Linux"],
            "document_keywords": ["RAG", "Install"],
            "document_questions": ["How do I install MimirQ?"],
        },
    )

    assert "[title] mimirq guide" in index_text
    assert "[section] setup / linux" in index_text
    assert "[keywords] rag, install" in index_text
    assert "[questions] how do i install mimirq?" in index_text
    assert index_text.endswith("install the package.")
    assert metadata["_retrieval_display_content"] == body
    assert metadata["retrieval_metadata_prefix_fields"] == ["title", "section", "keywords", "questions"]


def test_index_text_prefers_record_title_and_literal_section_question_metadata() -> None:
    import app.services.indexer as indexer_mod

    index_text, metadata = indexer_mod._chunk_index_content(
        "办理形式：网上办理",
        {
            "service_name": "优抚对象医疗保障",
            "document_title": "天宁区事项清单",
            "section": "政务服务事项知识",
            "question": "优抚对象医疗保障怎么办理？",
        },
    )

    assert index_text.startswith("[title] 优抚对象医疗保障")
    assert "[section] 政务服务事项知识" in index_text
    assert "[questions] 优抚对象医疗保障怎么办理?" in index_text
    assert metadata["retrieval_metadata_prefix_fields"] == ["title", "section", "questions"]
