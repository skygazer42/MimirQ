
import uuid
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.query.normalize import normalize_query
from app.types.indexing import EventEntityInput


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


def test_embedding_quota_gate_can_degrade_without_failing_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.indexer as indexer_mod
    import app.services.tenant_quota_service as quota_service

    events: list[tuple[str, str]] = []

    monkeypatch.setattr(indexer_mod.settings, "TENANT_QUOTA_FAIL_CLOSED", False, raising=False)
    monkeypatch.setattr(
        quota_service,
        "enforce_tenant_embedding_char_quota",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("quota backend unavailable")),
        raising=True,
    )
    monkeypatch.setattr(
        indexer_mod,
        "_persist_ingest_gate_outcome_best_effort",
        lambda *_args, **kwargs: events.append((kwargs["outcome"], kwargs["reason"])),
        raising=True,
    )
    monkeypatch.setattr(indexer_mod, "_audit_ingest_gate_event", lambda *_args, **_kwargs: None, raising=True)

    result = indexer_mod._enforce_embedding_quota_gate(
        object(),  # type: ignore[arg-type]
        tenant_id=UUID(int=1),
        document_id=UUID(int=2),
        additional_chars=123,
    )

    assert result["gate_outcome"] == "degraded"
    assert result["gate_reason"] == "tenant_quota_gate_unavailable"
    assert events == [("degraded", "tenant_quota_gate_unavailable")]


def test_embedding_quota_gate_can_fail_closed_on_quota_backend_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.indexer as indexer_mod
    import app.services.tenant_quota_service as quota_service

    monkeypatch.setattr(indexer_mod.settings, "TENANT_QUOTA_FAIL_CLOSED", True, raising=False)
    monkeypatch.setattr(
        quota_service,
        "enforce_tenant_embedding_char_quota",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("quota backend unavailable")),
        raising=True,
    )
    monkeypatch.setattr(indexer_mod, "_persist_ingest_gate_outcome_best_effort", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(indexer_mod, "_audit_ingest_gate_event", lambda *_args, **_kwargs: None, raising=True)

    with pytest.raises(quota_service.TenantQuotaExceededError) as exc_info:
        indexer_mod._enforce_embedding_quota_gate(
            object(),  # type: ignore[arg-type]
            tenant_id=UUID(int=1),
            document_id=UUID(int=2),
            additional_chars=123,
        )

    assert exc_info.value.quota == "embedding_chars_gate_unavailable"
    assert exc_info.value.meta["outcome"] == "closed"
    assert exc_info.value.meta["reason"] == "tenant_quota_gate_unavailable"


def test_index_chunks_tracks_vector_and_bm25_channel_transitions(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.indexer as indexer_mod

    class _StubMilvus:
        def add_vectors(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            return []

    class _FakeSession:
        def commit(self) -> None:
            return None

        def flush(self) -> None:
            return None

    monkeypatch.setattr(indexer_mod, "get_milvus_adapter", lambda **_k: _StubMilvus(), raising=True)
    monkeypatch.setattr(
        indexer_mod,
        "_enforce_embedding_quota_gate",
        lambda *_args, **_kwargs: {"gate_outcome": "ok", "gate_reason": "ok"},
        raising=True,
    )
    monkeypatch.setattr(
        indexer_mod.Indexer,
        "_load_document_for_channel_tracking",
        lambda *_args, **_kwargs: SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=UUID(int=1),
            dataset_id=None,
            filename="doc.txt",
            file_type="txt",
            doc_metadata={"pipeline_hash": "pipe-1", "active_pipeline_hash": "pipe-1"},
        ),
        raising=True,
    )
    monkeypatch.setattr(
        indexer_mod,
        "resolve_dataset_embedding_runtime",
        lambda *_args, **_kwargs: SimpleNamespace(
            embedding_space_hash="space-1",
            dataset_scoped=False,
            collection_name="default",
        ),
        raising=True,
    )
    monkeypatch.setattr(
        indexer_mod.Indexer,
        "_embedding_runtime_for_document",
        lambda *_args, **_kwargs: SimpleNamespace(
            embedding_space_hash="space-1",
            dataset_scoped=False,
            collection_name="default",
        ),
        raising=True,
    )

    transitions: list[tuple[str, str, bool, str | None]] = []
    monkeypatch.setattr(
        indexer_mod,
        "transition_document_index_channel",
        lambda _db, *, channel, status, increment_attempt=False, error=None, **_kwargs: transitions.append(
            (channel, status, increment_attempt, error)
        ),
        raising=True,
    )
    monkeypatch.setattr(indexer_mod.Indexer, "_index_chunk_vectors", lambda *_args, **_kwargs: ["vec-1"], raising=True)
    monkeypatch.setattr(
        indexer_mod.Indexer,
        "_persist_document_chunks",
        lambda *_args, **_kwargs: [SimpleNamespace(id=uuid.uuid4(), chunk_index=0, content="body")],
        raising=True,
    )
    monkeypatch.setattr(
        indexer_mod.Indexer,
        "_update_bm25_for_chunks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bm25 down")),
        raising=True,
    )

    indexer = indexer_mod.Indexer(_FakeSession())  # type: ignore[arg-type]
    indexer.index_chunks(
        tenant_id=UUID(int=1),
        document_id=UUID(int=2),
        chunks=[indexer_mod.ChunkInput(content="body", metadata={})],
        options=indexer_mod.IndexingOptions(chunk_vector_enabled=True, bm25_index_enabled=True),
    )

    assert transitions == [
        ("vector", "processing", True, None),
        ("vector", "ready", False, None),
        ("bm25", "processing", True, None),
        ("bm25", "error", False, "bm25 down"),
    ]


def test_index_events_tracks_event_and_entity_vector_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.indexer as indexer_mod

    class _StubMilvus:
        def add_vectors(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
            return []

    class _FakeSession:
        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def flush(self) -> None:
            return None

    monkeypatch.setattr(indexer_mod, "get_milvus_adapter", lambda **_k: _StubMilvus(), raising=True)
    monkeypatch.setattr(
        indexer_mod.Indexer,
        "_load_document_for_channel_tracking",
        lambda *_args, **_kwargs: SimpleNamespace(
            id=UUID(int=2),
            tenant_id=UUID(int=1),
            dataset_id=None,
            doc_metadata={"pipeline_hash": "pipe-1", "active_pipeline_hash": "pipe-1"},
        ),
        raising=True,
    )

    def _fake_get_or_create_entity(self, **_kwargs):  # noqa: ANN001, ANN003
        return SimpleNamespace(id=uuid.uuid4(), vector=None, extra_data=None, description=None)

    monkeypatch.setattr(indexer_mod.Indexer, "_get_or_create_entity", _fake_get_or_create_entity, raising=True)
    monkeypatch.setattr(indexer_mod, "KgEventEntity", lambda **kwargs: SimpleNamespace(**kwargs), raising=True)

    transitions: list[tuple[str, str, bool, str | None]] = []
    monkeypatch.setattr(
        indexer_mod,
        "transition_document_index_channel",
        lambda _db, *, channel, status, increment_attempt=False, error=None, **_kwargs: transitions.append(
            (channel, status, increment_attempt, error)
        ),
        raising=True,
    )
    monkeypatch.setattr(indexer_mod.Indexer, "_index_event_vectors", lambda *_args, **_kwargs: [], raising=True)
    monkeypatch.setattr(indexer_mod.Indexer, "_index_entity_vectors", lambda *_args, **_kwargs: ["entity-1"], raising=True)

    indexer = indexer_mod.Indexer(_FakeSession())  # type: ignore[arg-type]
    indexer.index_events(
        tenant_id=UUID(int=1),
        events=[
            indexer_mod.EventInput(
                title="t",
                summary="s",
                content="c",
                document_id=UUID(int=2),
                chunk_id=uuid.uuid4(),
                    references={"pipeline_hash": "pipe-1"},
                    vector=[0.1],
                    entities=[
                        EventEntityInput(
                            name="entity",
                            normalized_name="entity",
                            type="concept",
                        vector=[0.2],
                    )
                ],
            )
        ],
        commit=True,
        options=indexer_mod.IndexingOptions(event_vector_enabled=True, entity_vector_enabled=True),
    )

    assert transitions == [
        ("event_vector", "processing", True, None),
        ("event_vector", "error", False, "event_vector_write_failed"),
        ("entity_vector", "processing", True, None),
        ("entity_vector", "ready", False, None),
    ]
