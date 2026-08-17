from __future__ import annotations

import asyncio
import datetime as dt
import sys
import uuid
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from starlette import status as starlette_status

if not hasattr(dt, "UTC"):
    dt.UTC = dt.timezone.utc
if not hasattr(starlette_status, "HTTP_413_CONTENT_TOO_LARGE"):
    starlette_status.HTTP_413_CONTENT_TOO_LARGE = starlette_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
if not hasattr(starlette_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    starlette_status.HTTP_422_UNPROCESSABLE_CONTENT = starlette_status.HTTP_422_UNPROCESSABLE_ENTITY

from app.rag.kg.extraction import extractor as extractor_module


class _FakeQuery:
    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = list(rows or [])

    def filter(self, *_args, **_kwargs) -> _FakeQuery:
        return self

    def order_by(self, *_args, **_kwargs) -> _FakeQuery:
        return self

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, *, query_rows: list[object] | None = None) -> None:
        self.added: list[object] = []
        self.closed = False
        self.commits = 0
        self.rollbacks = 0
        self.query_rows = list(query_rows or [])

    def add_all(self, rows: list[object]) -> None:
        self.added.extend(rows)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True

    def expunge_all(self) -> None:
        return None

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        return _FakeQuery(self.query_rows)


@dataclass
class _FakeRelation:
    tenant_id: object
    pipeline_hash: object
    document_id: object
    chunk_id: object
    event_id: object
    subject_entity_id: object
    predicate: str
    predicate_raw: object
    object_entity_id: object
    confidence: float
    qualifiers: object
    references: dict[str, object]
    extra_data: dict[str, object]


@dataclass
class _FakeEventEntity:
    event_id: object
    entity_id: object
    weight: float
    role: str
    extra_data: dict[str, object] | None


class _FakeEmbedder:
    async def generate_batch(self, batch: list[str]) -> list[list[float]]:
        return [[] for _ in batch]


class _IndexerFactory:
    last_instance: _IndexerFactory | None = None

    def __init__(self, _session: _FakeSession) -> None:
        self.records: list[object] = []
        self.delete_calls: list[dict[str, object]] = []
        self.entities_upserted: list[dict[str, object]] = []
        type(self).last_instance = self

    def upsert(self, *, tenant_id: object, records: list[object], options: object) -> SimpleNamespace:
        self.records = list(records)
        events = [
            SimpleNamespace(id=f"event-{idx}", chunk_id=record.chunk_id, document_id=record.document_id)
            for idx, record in enumerate(self.records, start=1)
        ]
        return SimpleNamespace(event_result=SimpleNamespace(events=events, entities=[]))

    def upsert_entities(self, *, tenant_id: object, entities: list[dict[str, object]], options: object, commit: bool):
        self.entities_upserted.extend(entities)
        return []

    def delete_event_indexes_for_chunks(
        self,
        *,
        tenant_id: object,
        chunk_ids: list[object],
        exclude_event_ids: list[object],
        prune_orphan_entities: bool,
        commit: bool | None = None,
    ) -> None:
        self.delete_calls.append(
            {
                "tenant_id": tenant_id,
                "chunk_ids": list(chunk_ids),
                "exclude_event_ids": list(exclude_event_ids),
                "prune_orphan_entities": prune_orphan_entities,
                "commit": commit,
            }
        )


class _NoOpRelationRepository:
    def __init__(self, _session: _FakeSession) -> None:
        self.delete_calls: list[dict[str, object]] = []

    def delete_relations_for_chunks(self, chunk_ids: list[object], *, tenant_id: object, commit: bool) -> None:
        self.delete_calls.append({"chunk_ids": list(chunk_ids), "tenant_id": tenant_id, "commit": commit})


class _TrackingRelationRepository:
    last_instance: _TrackingRelationRepository | None = None

    def __init__(self, _session: _FakeSession) -> None:
        self.delete_calls: list[dict[str, object]] = []
        type(self).last_instance = self

    def delete_relations_for_chunks(self, chunk_ids: list[object], *, tenant_id: object, commit: bool) -> None:
        self.delete_calls.append({"chunk_ids": list(chunk_ids), "tenant_id": tenant_id, "commit": commit})


def _make_chunk(chunk_id: str, *, document_id: str, chunk_index: int, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=chunk_id,
        tenant_id="tenant-1",
        document_id=document_id,
        chunk_index=chunk_index,
        page_number=chunk_index + 1,
        start_char=chunk_index * 10,
        end_char=chunk_index * 10 + len(content),
        content=content,
        doc_metadata={},
    )


def _make_config(**overrides: object) -> SimpleNamespace:
    base = {
        "tenant_id": "tenant-1",
        "chunk_ids": [],
        "prompt_template_id": None,
        "prompt_template_key": None,
        "prompt_ab_experiment_key": None,
        "ab_user_key": None,
        "extraction_backend": None,
        "max_concurrency": 1,
        "replace_existing": False,
        "prune_orphan_entities": False,
        "extract_relations": False,
        "extract_skills": False,
        "kg_python_plugin": "",
        "kg_python_params": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_extract_state(
    *,
    chunks: list[SimpleNamespace],
    budget_skipped_chunk_ids: set[object] | None = None,
    replace_existing: bool = False,
    extract_relations_enabled: bool = False,
    extract_skills_enabled: bool = False,
) -> object:
    return extractor_module._ExtractState(
        tenant_id="tenant-1",
        resolved_chunks=chunks,
        budgeted_chunks=chunks,
        max_chunks_per_document=0,
        chunk_budget_strategy="uniform",
        budget_stats_by_doc={},
        budget_skipped_chunk_ids=set(budget_skipped_chunk_ids or set()),
        processor=object(),
        embedder=_FakeEmbedder(),
        backend_selection=SimpleNamespace(backend="llm", processor=object(), fallback_reason=None),
        backend_reason=None,
        prompt_template_content=None,
        chosen_template_id=None,
        max_concurrency=1,
        max_events_per_chunk=6,
        max_entities_per_event=30,
        embed_batch_size=128,
        chunk_timeout_sec=0.0,
        context_window=0,
        min_chars=0,
        chunk_max_retries=0,
        retry_backoff_sec=0.0,
        replace_existing=replace_existing,
        skip_unchanged=False,
        extract_relations_enabled=extract_relations_enabled,
        extract_skills_enabled=extract_skills_enabled,
        prompt_selector_expected={},
        chunk_hash_by_id={chunk.id: f"hash-{chunk.id}" for chunk in chunks},
        chunk_key_by_id={chunk.id: str(chunk.chunk_index) for chunk in chunks},
        chunk_len_by_id={chunk.id: len(chunk.content) for chunk in chunks},
        existing_events_by_chunk={},
        kept_events=[],
        chunks_to_process=chunks,
        chunk_id_to_pos={chunk.id: index for index, chunk in enumerate(chunks)},
        sem=asyncio.Semaphore(1),
    )


def _set_extract_defaults(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    defaults = {
        "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT": 0,
        "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY": "uniform",
        "KG_EXTRACT_LONG_DOC_BACKEND": "",
        "KG_EXTRACT_LONG_DOC_MIN_CHUNKS": 0,
        "KG_EXTRACT_MAX_CONCURRENCY": 0,
        "KG_EXTRACT_MAX_EVENTS_PER_CHUNK": 6,
        "KG_EXTRACT_MAX_ENTITIES_PER_EVENT": 30,
        "KG_EXTRACT_EMBED_BATCH_SIZE": 128,
        "KG_EXTRACT_CHUNK_TIMEOUT_SEC": 0,
        "KG_EXTRACT_CONTEXT_WINDOW_CHUNKS": 0,
        "KG_EXTRACT_MIN_CHARS": 0,
        "KG_EXTRACT_CHUNK_MAX_RETRIES": 0,
        "KG_EXTRACT_CHUNK_RETRY_BACKOFF_SEC": 0.0,
        "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS": False,
        "KG_EXTRACT_ENTITY_VERIFY_ENABLED": False,
        "KG_EXTRACT_RELATION_VERIFY_ENABLED": False,
        "KG_EXTRACT_EVIDENCE_REQUIRED": False,
        "KG_RELATION_ENABLED": False,
        "KG_RELATION_ALIAS_HEURISTIC_ENABLED": False,
        "KG_RELATION_ALLOWED_PREDICATES": "",
        "KG_RELATION_MAX_RELATIONS_PER_CHUNK": 20,
        "KG_SKILL_ENABLED": False,
        "KG_SKILL_MAX_SKILLS_PER_CHUNK": 3,
        "KG_SKILL_EVIDENCE_REQUIRED": False,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setattr(extractor_module.settings, key, value, raising=False)


def test_apply_document_chunk_budget_preserves_global_order_per_document() -> None:
    chunks = [
        _make_chunk("doc-a-0", document_id="doc-a", chunk_index=0, content="A0"),
        _make_chunk("doc-b-0", document_id="doc-b", chunk_index=0, content="B0"),
        _make_chunk("doc-a-1", document_id="doc-a", chunk_index=1, content="A1"),
        _make_chunk("doc-b-1", document_id="doc-b", chunk_index=1, content="B1"),
        _make_chunk("doc-a-2", document_id="doc-a", chunk_index=2, content="A2"),
    ]

    kept, stats = extractor_module._apply_document_chunk_budget(
        chunks,
        max_chunks_per_document=2,
        strategy="head",
    )

    assert [chunk.id for chunk in kept] == ["doc-a-0", "doc-b-0", "doc-a-1", "doc-b-1"]
    assert stats == {
        "doc-a": {"strategy": "head", "total": 3, "kept": 2, "skipped": 1},
        "doc-b": {"strategy": "head", "total": 2, "kept": 2, "skipped": 0},
    }


@pytest.mark.asyncio
async def test_extract_preserves_budget_section_order_and_retry_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_extract_defaults(
        monkeypatch,
        KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT=2,
        KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY="head",
        KG_EXTRACT_CONTEXT_WINDOW_CHUNKS=1,
        KG_EXTRACT_CHUNK_MAX_RETRIES=1,
    )

    session = _FakeSession()
    monkeypatch.setattr(extractor_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(extractor_module, "DocumentProcessor", _FakeEmbedder)
    monkeypatch.setattr(extractor_module, "Indexer", _IndexerFactory)
    monkeypatch.setattr(extractor_module, "RelationRepository", _NoOpRelationRepository)
    monkeypatch.setattr(extractor_module, "create_llm_client", lambda **_kwargs: _async_value(object()))

    writeback: dict[str, object] = {}
    metrics: list[dict[str, object]] = []

    class _RetryProcessor:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.failures = {"chunk-1": 1}

        async def extract_from_sections(
            self,
            sections: list[SimpleNamespace],
            *,
            batch_index: int,
            max_events: int,
            max_entities_per_event: int,
        ) -> list[dict[str, object]]:
            chunk_id = sections[0].id
            self.calls.append(
                {
                    "chunk_id": chunk_id,
                    "sections": [section.id for section in sections],
                    "batch_index": batch_index,
                    "max_events": max_events,
                    "max_entities_per_event": max_entities_per_event,
                }
            )
            if self.failures.get(chunk_id, 0) > 0:
                self.failures[chunk_id] -= 1
                raise RuntimeError("retry once")
            return [{"title": f"Title {chunk_id}", "summary": "summary", "content": "content", "entities": []}]

    processor = _RetryProcessor()
    monkeypatch.setattr(
        extractor_module,
        "resolve_extraction_backend",
        lambda **_kwargs: SimpleNamespace(backend="llm", processor=processor, fallback_reason=None),
    )
    monkeypatch.setattr(
        extractor_module.EventExtractor,
        "_writeback_document_metadata",
        lambda self, **kwargs: writeback.update(kwargs),
    )
    monkeypatch.setattr(extractor_module, "log_metrics", lambda payload: metrics.append(dict(payload)))

    chunks = [
        _make_chunk("chunk-3", document_id="doc-1", chunk_index=2, content="third"),
        _make_chunk("chunk-1", document_id="doc-1", chunk_index=0, content="first"),
        _make_chunk("chunk-2", document_id="doc-1", chunk_index=1, content="second"),
    ]

    events = await extractor_module.EventExtractor().extract(_make_config(), chunks=chunks)

    assert [event.chunk_id for event in events] == ["chunk-1", "chunk-2"]
    assert [call["chunk_id"] for call in processor.calls].count("chunk-1") == 2
    assert [call["chunk_id"] for call in processor.calls].count("chunk-2") == 1
    assert processor.calls[0]["sections"] == ["chunk-1", "chunk-2"]
    assert any(call["sections"] == ["chunk-2", "chunk-1"] for call in processor.calls)
    assert writeback["budget_skipped_chunk_ids"] == {"chunk-3"}
    assert writeback["retry_chunk_ids"] == {"chunk-1"}
    assert metrics[-1]["chunk_budget_skipped"] == 1
    assert metrics[-1]["retry_chunks"] == 1
    assert metrics[-1]["retry_attempts"] == 1


@pytest.mark.asyncio
async def test_extract_raises_when_every_attempted_chunk_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_extract_defaults(
        monkeypatch,
        KG_EXTRACT_CHUNK_MAX_RETRIES=1,
        KG_EXTRACT_CHUNK_RETRY_BACKOFF_SEC=0.0,
    )

    session = _FakeSession()
    monkeypatch.setattr(extractor_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(extractor_module, "DocumentProcessor", _FakeEmbedder)
    monkeypatch.setattr(extractor_module, "create_llm_client", lambda **_kwargs: _async_value(object()))

    class _FailingProcessor:
        async def extract_from_sections(
            self,
            sections: list[SimpleNamespace],
            *,
            batch_index: int,
            max_events: int,
            max_entities_per_event: int,
        ) -> list[dict[str, object]]:
            raise ValueError(f"boom:{sections[0].id}")

    monkeypatch.setattr(
        extractor_module,
        "resolve_extraction_backend",
        lambda **_kwargs: SimpleNamespace(backend="llm", processor=_FailingProcessor(), fallback_reason=None),
    )

    chunk = _make_chunk("chunk-fail", document_id="doc-fail", chunk_index=0, content="failing chunk")

    with pytest.raises(RuntimeError, match=r"KG extraction failed for all attempted chunks \(1\); boom:chunk-fail"):
        await extractor_module.EventExtractor().extract(_make_config(), chunks=[chunk])

    assert session.rollbacks >= 1
    assert session.closed is True


@pytest.mark.asyncio
async def test_extract_timeout_does_not_return_existing_events_without_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_extract_defaults(monkeypatch, KG_EXTRACT_CHUNK_TIMEOUT_SEC=0.001)

    existing_event = SimpleNamespace(chunk_id="chunk-timeout")
    session = _FakeSession(query_rows=[existing_event])
    monkeypatch.setattr(extractor_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(extractor_module, "DocumentProcessor", _FakeEmbedder)
    monkeypatch.setattr(extractor_module, "create_llm_client", lambda **_kwargs: _async_value(object()))

    class _SlowProcessor:
        async def extract_from_sections(
            self,
            sections: list[SimpleNamespace],
            *,
            batch_index: int,
            max_events: int,
            max_entities_per_event: int,
        ) -> list[dict[str, object]]:
            del sections, batch_index, max_events, max_entities_per_event
            await asyncio.sleep(0.01)
            return []

    monkeypatch.setattr(
        extractor_module,
        "resolve_extraction_backend",
        lambda **_kwargs: SimpleNamespace(backend="llm", processor=_SlowProcessor(), fallback_reason=None),
    )
    writeback: dict[str, object] = {}
    monkeypatch.setattr(
        extractor_module.EventExtractor,
        "_writeback_document_metadata",
        lambda self, **kwargs: writeback.update(kwargs),
    )
    monkeypatch.setattr(extractor_module, "log_metrics", lambda _payload: None)

    chunk = _make_chunk(
        "chunk-timeout",
        document_id="doc-timeout",
        chunk_index=0,
        content="slow chunk",
    )
    events = await extractor_module.EventExtractor().extract(
        _make_config(replace_existing=False),
        chunks=[chunk],
    )

    assert events == []
    assert writeback["kept_events"] == []
    assert writeback["failed_chunk_ids"] == {"chunk-timeout"}


@pytest.mark.asyncio
async def test_extract_relation_verifier_fails_open_to_original_relations(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_extract_defaults(
        monkeypatch,
        KG_RELATION_ENABLED=True,
        KG_EXTRACT_RELATION_VERIFY_ENABLED=True,
    )

    session = _FakeSession()
    monkeypatch.setattr(extractor_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(extractor_module, "DocumentProcessor", _FakeEmbedder)
    monkeypatch.setattr(extractor_module, "Indexer", _RelationIndexer)
    monkeypatch.setattr(extractor_module, "RelationRepository", _NoOpRelationRepository)
    monkeypatch.setattr(extractor_module, "KgRelation", _FakeRelation)
    monkeypatch.setattr(extractor_module, "create_llm_client", lambda **_kwargs: _async_value(object()))
    monkeypatch.setitem(
        sys.modules,
        "app.rag.kg.ontology",
        SimpleNamespace(resolve_allowed_predicates=lambda **_kwargs: ("works_for",)),
    )

    class _EventProcessor:
        async def extract_from_sections(
            self,
            sections: list[SimpleNamespace],
            *,
            batch_index: int,
            max_events: int,
            max_entities_per_event: int,
        ) -> list[dict[str, object]]:
            return [
                {
                    "title": "Alice at Acme",
                    "summary": "Alice works for Acme",
                    "content": "Alice works for Acme",
                    "entities": [
                        {"name": "Alice", "type": "Person", "evidence_quote": "Alice"},
                        {"name": "Acme", "type": "Organization", "evidence_quote": "Acme"},
                    ],
                }
            ]

    class _FakeRelationProcessor:
        def __init__(self, *, llm_client: object, allowed_predicates: tuple[str, ...]) -> None:
            self.allowed_predicates = allowed_predicates

        async def extract_relations(
            self,
            *,
            text: str,
            candidates: list[object],
            max_relations: int,
        ) -> list[dict[str, object]]:
            assert [candidate.cid for candidate in candidates] == ["E1", "E2"]
            return [
                {
                    "subject_id": "E1",
                    "predicate": "works_for",
                    "object_id": "E2",
                    "confidence": 0.9,
                    "evidence_quote": "Alice works for Acme",
                }
            ]

    class _FakeRelationVerifier:
        def __init__(self, *, llm_client: object, allowed_predicates: tuple[str, ...]) -> None:
            self.allowed_predicates = allowed_predicates

        async def verify(
            self,
            *,
            text: str,
            candidates: list[object],
            max_keep: int,
        ) -> dict[str, object]:
            return {"kept": []}

    monkeypatch.setattr(
        extractor_module,
        "resolve_extraction_backend",
        lambda **_kwargs: SimpleNamespace(backend="llm", processor=_EventProcessor(), fallback_reason=None),
    )
    monkeypatch.setattr(extractor_module, "RelationProcessor", _FakeRelationProcessor)
    monkeypatch.setattr(extractor_module, "RelationVerifier", _FakeRelationVerifier)
    monkeypatch.setattr(extractor_module, "log_metrics", lambda payload: None)
    monkeypatch.setattr(
        extractor_module.EventExtractor,
        "_writeback_document_metadata",
        lambda self, **kwargs: None,
    )

    chunk = _make_chunk("chunk-rel", document_id="doc-rel", chunk_index=0, content="Alice works for Acme.")

    events = await extractor_module.EventExtractor().extract(
        _make_config(extract_relations=True),
        chunks=[chunk],
    )

    relation_rows = [row for row in session.added if isinstance(row, _FakeRelation)]
    assert len(events) == 1
    assert len(relation_rows) == 1
    assert relation_rows[0].predicate == "works_for"
    assert relation_rows[0].subject_entity_id == "entity-alice"
    assert relation_rows[0].object_entity_id == "entity-acme"
    assert relation_rows[0].references["evidence_quote"] == "Alice works for Acme"


class _RelationIndexer(_IndexerFactory):
    def upsert(self, *, tenant_id: object, records: list[object], options: object) -> SimpleNamespace:
        self.records = list(records)
        events = [SimpleNamespace(id="event-1", chunk_id=records[0].chunk_id, document_id=records[0].document_id)]
        entities = [
            SimpleNamespace(id="entity-alice", normalized_name="alice", type="Person"),
            SimpleNamespace(id="entity-acme", normalized_name="acme", type="Organization"),
        ]
        return SimpleNamespace(event_result=SimpleNamespace(events=events, entities=entities))


@pytest.mark.asyncio
async def test_relation_post_index_pass_replaces_processed_and_budget_skipped_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_extract_defaults(
        monkeypatch,
        KG_RELATION_ENABLED=True,
        KG_RELATION_ALIAS_HEURISTIC_ENABLED=False,
    )

    session = _FakeSession()
    indexer = _IndexerFactory(session)
    chunk_keep = _make_chunk("chunk-keep", document_id="doc-rel", chunk_index=0, content="Alice")
    chunk_skip = _make_chunk("chunk-skip", document_id="doc-rel", chunk_index=1, content="Budget skipped")
    state = _make_extract_state(
        chunks=[chunk_keep, chunk_skip],
        budget_skipped_chunk_ids={"chunk-skip"},
        replace_existing=True,
        extract_relations_enabled=True,
    )

    class _UnusedRelationProcessor:
        def __init__(self, *, llm_client: object, allowed_predicates: tuple[str, ...]) -> None:
            self.allowed_predicates = allowed_predicates

        async def extract_relations(
            self,
            *,
            text: str,
            candidates: list[object],
            max_relations: int,
        ) -> list[dict[str, object]]:
            raise AssertionError("relation extraction should not run for <2 candidates")

    monkeypatch.setattr(extractor_module, "RelationProcessor", _UnusedRelationProcessor)
    monkeypatch.setattr(extractor_module, "RelationRepository", _TrackingRelationRepository)
    monkeypatch.setitem(
        sys.modules,
        "app.rag.kg.ontology",
        SimpleNamespace(resolve_allowed_predicates=lambda **_kwargs: ("works_for",)),
    )

    processed_events = [
        (
            chunk_keep,
            {
                "entities": [
                    {
                        "name": "Alice",
                        "normalized_name": "alice",
                        "type": "Person",
                        "_cid": "E1",
                    }
                ]
            },
        )
    ]
    context = extractor_module._RelationPostIndexContext(
        session=session,
        config=_make_config(replace_existing=True, extract_relations=True),
        index_options=None,
        indexer=indexer,
        state=state,
        processed_events=processed_events,
        result=SimpleNamespace(entities=[SimpleNamespace(id="entity-alice", normalized_name="alice", type="Person")]),
        cleanup_chunk_ids=["chunk-keep"],
        llm_client=object(),
        alias_diag=extractor_module.EventExtractor._new_alias_diag(),
        alias_stats_by_doc={},
        llm_aliases_by_chunk={},
        relation_verify_enabled=False,
        chosen_template_id=None,
        evidence_required=False,
    )

    stats = await extractor_module.EventExtractor()._run_relation_post_index_pass(context)

    repo = _TrackingRelationRepository.last_instance
    assert stats == {
        "total_raw": 0,
        "kept": 0,
        "dropped_no_evidence": 0,
        "dropped_missing_endpoints": 0,
    }
    assert repo is not None
    assert repo.delete_calls == [{"chunk_ids": ["chunk-keep", "chunk-skip"], "tenant_id": "tenant-1", "commit": False}]
    assert session.added == []
    assert session.commits == 1


@pytest.mark.asyncio
async def test_skill_post_index_pass_links_upserted_skills_to_new_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_extract_defaults(
        monkeypatch,
        KG_SKILL_ENABLED=True,
        KG_SKILL_MAX_SKILLS_PER_CHUNK=2,
        KG_SKILL_EVIDENCE_REQUIRED=False,
    )

    session = _FakeSession()
    indexer = _IndexerFactory(session)
    document_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    chunk = _make_chunk(chunk_id, document_id=document_id, chunk_index=0, content="Use Python to automate.")
    state = _make_extract_state(
        chunks=[chunk],
        extract_relations_enabled=False,
        extract_skills_enabled=True,
    )

    class _FakeSkillProcessor:
        def __init__(self, *, llm_client: object) -> None:
            self.llm_client = llm_client

        async def extract_skills(self, *, text: str, max_skills: int) -> list[dict[str, object]]:
            return [
                {
                    "name": "Python Automation",
                    "summary": "Automate tasks with Python",
                    "confidence": 0.8,
                    "evidence_quote": "Python to automate",
                    "tags": ["python"],
                }
            ]

    def _upsert_entities(*, tenant_id: object, entities: list[dict[str, object]], options: object, commit: bool):
        indexer.entities_upserted.extend(entities)
        return [SimpleNamespace(id="skill-1", normalized_name="python automation", type="Skill")]

    monkeypatch.setattr(extractor_module, "SkillProcessor", _FakeSkillProcessor)
    monkeypatch.setattr(extractor_module, "KgEventEntity", _FakeEventEntity)
    monkeypatch.setattr(indexer, "upsert_entities", _upsert_entities)

    context = extractor_module._SkillPostIndexContext(
        session=session,
        config=_make_config(extract_skills=True),
        index_options=None,
        indexer=indexer,
        state=state,
        cleanup_chunk_ids=[chunk_id],
        llm_client=object(),
        chosen_template_id=None,
        evidence_required=False,
        new_events=[SimpleNamespace(id="event-1", chunk_id=chunk_id, document_id=document_id)],
    )

    stats = await extractor_module.EventExtractor()._run_skill_post_index_pass(context)

    skill_links = [row for row in session.added if isinstance(row, _FakeEventEntity)]
    assert stats["total_raw"] == 1
    assert stats["kept"] == 1
    assert len(indexer.entities_upserted) == 1
    assert indexer.entities_upserted[0]["normalized_name"] == "python automation"
    assert len(skill_links) == 1
    assert skill_links[0].event_id == "event-1"
    assert skill_links[0].entity_id == "skill-1"
    assert skill_links[0].role == "skill"
    assert session.commits == 1


async def _async_value(value: object) -> object:
    return value
