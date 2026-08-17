import asyncio
import datetime as dt
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import starlette.status as starlette_status
from langchain_core.documents import Document

if not hasattr(dt, "UTC"):
    dt.UTC = timezone.utc

if not hasattr(starlette_status, "HTTP_413_CONTENT_TOO_LARGE"):
    starlette_status.HTTP_413_CONTENT_TOO_LARGE = 413
if not hasattr(starlette_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    starlette_status.HTTP_422_UNPROCESSABLE_CONTENT = 422


class _Message:
    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content

    def model_dump(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class _Field:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> tuple[str, str, object]:
        return ("eq", self.name, other)

    def in_(self, values: list[object]) -> tuple[str, str, list[object]]:
        return ("in", self.name, values)


def test_event_processor_template_fallback_and_entity_merge() -> None:
    from app.rag.kg.extraction.processor import EventProcessor

    prompts: list[str] = []

    class _LLM:
        async def chat_with_schema(self, messages, **_kwargs):
            prompts.append(messages[0].content)
            return {
                "events": [
                    {
                        "title": "",
                        "summary": "Summary sentence for the extracted event.",
                        "schema_version": "v1",
                        "event_schema": "incident",
                        "entities": [
                            {
                                "name": "Alice",
                                "type": "Person",
                                "description": "short",
                                "role": "",
                                "weight": 0.4,
                                "evidence_quote": "",
                                "source_span": {"source": "context", "start_char": 1, "end_char": 2},
                            },
                            {
                                "name": "alice",
                                "type": "person",
                                "description": "much longer description",
                                "role": "speaker",
                                "weight": 0.8,
                                "evidence_quote": "Alice",
                                "source_span": {"source": "target", "start_char": 5, "end_char": 10},
                            },
                            "Fallback Entity",
                        ],
                    }
                ]
            }

    processor = EventProcessor(_LLM(), prompt_template="Use template {missing_key}")
    processor.parser = SimpleNamespace(
        normalize_name=lambda value: str(value).strip().lower(),
        normalize_type=lambda value: str(value).strip().lower(),
    )
    sections = [
        SimpleNamespace(id=uuid4(), content="Primary chunk", page_number=3),
        SimpleNamespace(id=uuid4(), content="Neighbor chunk", page_number=4),
    ]

    result = asyncio.run(processor.extract_from_sections(sections, batch_index=7))

    assert prompts == ["Use template {missing_key}\n\n[Target p3] Primary chunk\n\n[Context 1 p4] Neighbor chunk"]
    assert result == [
        {
            "title": "Summary sentence for the extracted event.",
            "summary": "Summary sentence for the extracted event.",
            "content": "Summary sentence for the extracted event.",
            "schema_version": "v1",
            "event_schema": "incident",
            "entities": [
                {
                    "name": "Alice",
                    "normalized_name": "alice",
                    "type": "person",
                    "description": "much longer description",
                    "role": "speaker",
                    "weight": 0.4,
                    "evidence_quote": "Alice",
                    "evidence_source": "context",
                    "evidence_start_char": 1,
                    "evidence_end_char": 2,
                },
                {
                    "name": "Fallback Entity",
                    "normalized_name": "fallback entity",
                    "type": "unknown",
                    "description": "",
                    "role": None,
                    "weight": None,
                    "evidence_quote": None,
                    "evidence_source": None,
                    "evidence_start_char": None,
                    "evidence_end_char": None,
                },
            ],
            "chunk_id": str(sections[0].id),
        }
    ]


def test_prepare_chat_request_runtime_preserves_scope_on_dataset_failure_and_orders_memory_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_bootstrap_runtime as runtime

    scope_dataset_id = uuid4()
    history_item = _Message("user", "history message")
    request = SimpleNamespace(
        rag_config=SimpleNamespace(model_fields_set=set()),
        model_fields_set=set(),
        prompt_template_id=None,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        rag_config_template_id=None,
        rag_config_template_key=None,
        rag_config_ab_experiment_key=None,
        history=[history_item],
        enable_summary_memory=True,
        enable_structured_memory=True,
    )

    monkeypatch.setattr(runtime, "load_dataset_metadata", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(
        runtime,
        "merge_prompt_defaults_with_dataset",
        lambda **_kwargs: (None, "prompt-key", "prompt-exp", []),
    )
    monkeypatch.setattr(
        runtime,
        "merge_rag_config_template_defaults_with_dataset",
        lambda **_kwargs: (None, None, None, []),
    )
    monkeypatch.setattr(runtime, "get_conversation_summary", lambda *_args, **_kwargs: "SUMMARY")
    monkeypatch.setattr(runtime, "_retrieve_structured_memory_records", lambda **_kwargs: ["record"])
    monkeypatch.setattr(runtime, "build_structured_memory_context", lambda **_kwargs: "STRUCTURED")
    monkeypatch.setattr(runtime.settings, "STRUCTURED_MEMORY_ENABLED", True, raising=False)

    prepared = runtime.prepare_chat_request_runtime(
        db=object(),
        tenant_id=uuid4(),
        account_id="acct",
        request=request,
        conversation_id=uuid4(),
        scope_dataset_id=scope_dataset_id,
        document_ids=[],
        long_term_messages=[{"role": "assistant", "content": "memory"}],
        request_id="req-1",
    )

    assert prepared.dataset_id_used == scope_dataset_id
    assert prepared.dataset_rag_defaults_applied_fields == []
    assert prepared.effective_prompt_template_key == "prompt-key"
    assert prepared.effective_prompt_ab_experiment_key == "prompt-exp"
    assert prepared.history_for_llm == [
        {"role": "system", "content": "STRUCTURED"},
        {"role": "system", "content": "SUMMARY"},
        {"role": "user", "content": "history message"},
        {"role": "assistant", "content": "memory"},
    ]


def test_prepare_chat_request_runtime_keeps_template_metadata_when_usage_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_bootstrap_runtime as runtime

    chosen = SimpleNamespace(
        id=uuid4(),
        template_key="adaptive",
        version=3,
        ab_experiment_key="exp-1",
        ab_variant="B",
        config_patch={"top_k": 9},
        usage_count=0,
    )
    rollback_calls: list[str] = []

    class _DB:
        def commit(self) -> None:
            raise RuntimeError("commit failed")

        def rollback(self) -> None:
            rollback_calls.append("rollback")

    request = SimpleNamespace(
        rag_config=SimpleNamespace(model_fields_set=set()),
        model_fields_set=set(),
        prompt_template_id=None,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        rag_config_template_id=None,
        rag_config_template_key=None,
        rag_config_ab_experiment_key=None,
        history=[],
        enable_summary_memory=False,
        enable_structured_memory=False,
    )

    monkeypatch.setattr(runtime, "load_dataset_metadata", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runtime, "merge_rag_config_with_dataset_defaults", lambda **kwargs: (kwargs["rag_config"], []))
    monkeypatch.setattr(runtime, "merge_prompt_defaults_with_dataset", lambda **_kwargs: (None, None, None, []))
    monkeypatch.setattr(
        runtime,
        "merge_rag_config_template_defaults_with_dataset",
        lambda **_kwargs: (chosen.id, chosen.template_key, chosen.ab_experiment_key, ["template_default"]),
    )
    monkeypatch.setattr(
        runtime,
        "resolve_rag_config_template",
        lambda **_kwargs: (chosen, {"strategy": "adaptive_epsilon_greedy", "decision": "chosen"}),
    )
    monkeypatch.setattr(
        runtime,
        "apply_rag_config_patch",
        lambda **kwargs: (kwargs["rag_config"], ["top_k"]),
    )
    monkeypatch.setattr(runtime, "build_rag_config_patch_hash", lambda _patch: "patch-hash")
    monkeypatch.setattr(
        runtime,
        "build_adaptive_routing_reward_writeback",
        lambda **_kwargs: {"enabled": True},
    )

    prepared = runtime.prepare_chat_request_runtime(
        db=_DB(),
        tenant_id=uuid4(),
        account_id="acct",
        request=request,
        conversation_id=None,
        scope_dataset_id=None,
        document_ids=[],
        long_term_messages=[],
        request_id="req-2",
    )

    assert prepared.dataset_rag_config_template_defaults_applied_fields == ["template_default"]
    assert prepared.rag_config_template_meta == {
        "template_id": str(chosen.id),
        "template_key": "adaptive",
        "version": 3,
        "ab_experiment_key": "exp-1",
        "ab_variant": "B",
        "patch_hash": "patch-hash",
        "patch_applied_fields": ["top_k"],
        "resolver_debug": {"strategy": "adaptive_epsilon_greedy", "decision": "chosen"},
        "reward_writeback": {"enabled": True},
    }
    assert rollback_calls == ["rollback"]
    assert chosen.usage_count == 1


@pytest.mark.asyncio
async def test_stream_langchain_chat_session_events_persists_done_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.chat_stream_langchain as stream_module
    from app.services.chat_runtime import ChatStreamPersistInput

    cached_payloads: list[dict[str, object]] = []
    persisted_payloads: list[ChatStreamPersistInput] = []
    assistant_message_id = uuid4()

    async def _produce(*, queue, **_kwargs) -> None:
        await queue.put({"type": "token", "data": {"content": "Hello"}})
        await queue.put({"type": "citations", "data": [{"id": "c1"}]})
        await queue.put(
            {
                "type": "done",
                "data": {
                    "metrics": {"latency_ms": 12},
                    "structured_data": {"answer": "ok"},
                },
            }
        )
        await queue.put(None)

    monkeypatch.setattr(stream_module, "produce_langchain_stream_events", _produce)
    monkeypatch.setattr(
        stream_module,
        "annotate_chat_cache_metrics",
        lambda metrics, **kwargs: dict(metrics, cache=kwargs),
    )
    monkeypatch.setattr(
        stream_module,
        "apply_chat_runtime_metrics_context",
        lambda metrics, **_kwargs: dict(metrics, context_applied=True),
    )
    monkeypatch.setattr(
        stream_module,
        "store_chat_response_cache_if_needed",
        lambda **kwargs: cached_payloads.append(kwargs),
    )
    monkeypatch.setattr(
        stream_module,
        "dispatch_chat_stream_persistence",
        lambda **kwargs: persisted_payloads.append(kwargs["options"]),
    )

    options = stream_module.LangChainChatStreamSessionInput(
        execution=SimpleNamespace(
            db="db",
            request_id="req-stream",
            dataset_id_used=uuid4(),
            rag_config_template_meta={"template": "x"},
        ),
        cache_feature_enabled=True,
        cache_hit=False,
        cache_skip_reason="miss",
        cache_eligible=True,
        cache_key="cache-key",
        dataset_rag_defaults_applied_fields=["top_k"],
        dataset_rag_config_template_defaults_applied_fields=["template_default"],
        dataset_prompt_defaults_applied_fields=["prompt_default"],
        tenant_qps_meta={"enabled": True},
        quota_meta={"enabled": True},
        heartbeat_sec=0.0,
        disconnect_check=None,
        persist_in_background=False,
        spawn_background_task=lambda _task: None,
        persist_options=ChatStreamPersistInput(
            tenant_id=uuid4(),
            conversation_id=uuid4(),
            account_id="acct",
            assistant_message_id=assistant_message_id,
            request_id="req-stream",
            question="hello",
            document_count=2,
            content="",
            citations=[],
            metrics={},
            dataset_id_used=None,
            cache_hit=False,
            cache_key="cache-key",
            cache_eligible=True,
            structured_data=None,
            ip=None,
            user_agent=None,
            enable_summary_memory=False,
            enable_structured_memory=False,
        ),
    )

    events = [payload async for payload in stream_module.stream_langchain_chat_session_events(engine=object(), options=options)]

    assert len(events) == 3
    assert '"request_id": "req-stream"' in events[0]
    assert '"type": "citations"' in events[1]
    assert f'"assistant_message_id": "{assistant_message_id}"' in events[2]
    assert cached_payloads == [
        {
            "cache_eligible": True,
            "cache_hit": False,
            "cache_key": "cache-key",
            "content": "Hello",
            "citations": [{"id": "c1"}],
                "metrics": {
                    "latency_ms": 12,
                    "cache": {"enabled": True, "hit": False, "skip_reason": "miss"},
                    "context_applied": True,
                },
                "structured_data": {"answer": "ok"},
            }
        ]
    assert len(persisted_payloads) == 1
    assert persisted_payloads[0].content == "Hello"
    assert persisted_payloads[0].citations == [{"id": "c1"}]
    assert persisted_payloads[0].metrics == {
        "latency_ms": 12,
        "cache": {"enabled": True, "hit": False, "skip_reason": "miss"},
        "context_applied": True,
    }
    assert persisted_payloads[0].structured_data == {"answer": "ok"}


@pytest.mark.asyncio
async def test_stream_langchain_chat_session_events_skips_finalize_after_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_stream_langchain as stream_module
    from app.services.chat_runtime import ChatStreamPersistInput

    persisted: list[str] = []

    async def _produce(**_kwargs) -> None:
        await asyncio.Event().wait()

    async def _disconnect() -> bool:
        return True

    monkeypatch.setattr(stream_module, "produce_langchain_stream_events", _produce)
    monkeypatch.setattr(
        stream_module,
        "store_chat_response_cache_if_needed",
        lambda **_kwargs: persisted.append("cache"),
    )
    monkeypatch.setattr(
        stream_module,
        "dispatch_chat_stream_persistence",
        lambda **_kwargs: persisted.append("persist"),
    )

    options = stream_module.LangChainChatStreamSessionInput(
        execution=SimpleNamespace(
            db="db",
            request_id="req-disconnect",
            dataset_id_used=None,
            rag_config_template_meta=None,
        ),
        cache_feature_enabled=False,
        cache_hit=False,
        cache_skip_reason=None,
        cache_eligible=False,
        cache_key=None,
        dataset_rag_defaults_applied_fields=None,
        dataset_rag_config_template_defaults_applied_fields=None,
        dataset_prompt_defaults_applied_fields=None,
        tenant_qps_meta=None,
        quota_meta=None,
        heartbeat_sec=0.0,
        disconnect_check=_disconnect,
        persist_in_background=False,
        spawn_background_task=lambda _task: None,
        persist_options=ChatStreamPersistInput(
            tenant_id=uuid4(),
            conversation_id=uuid4(),
            account_id="acct",
            assistant_message_id=uuid4(),
            request_id="req-disconnect",
            question="hello",
            document_count=0,
            content="",
            citations=[],
            metrics={},
            dataset_id_used=None,
            cache_hit=False,
            cache_key=None,
            cache_eligible=False,
            structured_data=None,
            ip=None,
            user_agent=None,
            enable_summary_memory=False,
            enable_structured_memory=False,
        ),
    )

    events = [payload async for payload in stream_module.stream_langchain_chat_session_events(engine=object(), options=options)]

    assert events == []
    assert persisted == []


def test_pptx_parser_extracts_tables_and_text_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.parsing.parsers.pptx_parser as parser_module

    class _Cell:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Table:
        rows = [object(), object()]
        columns = [object(), object()]

        def cell(self, row: int, col: int) -> _Cell:
            values = {
                (0, 0): _Cell("A|1"),
                (0, 1): _Cell("B"),
                (1, 0): _Cell("C"),
                (1, 1): _Cell("D"),
            }
            return values[(row, col)]

    class _BrokenShape:
        has_text_frame = True

        @property
        def text_frame(self):
            raise RuntimeError("ignore me")

    table_shape = SimpleNamespace(has_table=True, table=_Table())
    text_shape = SimpleNamespace(
        has_table=False,
        has_text_frame=True,
        text_frame=SimpleNamespace(
            paragraphs=[
                SimpleNamespace(text="Main point", level=0),
                SimpleNamespace(text="Nested point", level=1),
            ]
        ),
    )
    presentation = SimpleNamespace(slides=[SimpleNamespace(shapes=[table_shape, text_shape, _BrokenShape()])])
    monkeypatch.setattr(parser_module, "Presentation", lambda _path: presentation)

    documents = parser_module.PptxParser().parse(Path("slides.pptx"))

    assert len(documents) == 1
    assert documents[0].page_content == "| A\\|1 | B |\n| --- | --- |\n| C | D |\n- Main point\n  - Nested point"
    assert documents[0].metadata == {
        "source": "slides.pptx",
        "page": 1,
        "total_pages": 1,
        "file_type": "pptx",
    }


def test_pptx_parser_returns_empty_document_when_no_slide_content(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.parsing.parsers.pptx_parser as parser_module

    monkeypatch.setattr(
        parser_module,
        "Presentation",
        lambda _path: SimpleNamespace(slides=[SimpleNamespace(shapes=[]), SimpleNamespace(shapes=[])]),
    )

    documents = parser_module.PptxParser().parse(Path("blank.pptx"))

    assert len(documents) == 1
    assert documents[0].page_content == ""
    assert documents[0].metadata == {
        "source": "blank.pptx",
        "total_pages": 2,
        "file_type": "pptx",
    }


def test_jsonl_records_chunker_preserves_fallback_and_record_overlap_metadata() -> None:
    from app.rag.chunking.strategies.jsonl_records import JsonlRecordsChunker

    chunker = JsonlRecordsChunker(chunk_size=17, chunk_overlap=10)

    class _FallbackSplitter:
        def create_documents(self, *, texts, metadatas):
            return [Document(page_content="alpha", metadata={"start_index": 2, "extra": metadatas[0]["source"]})]

    chunker._fallback_splitter = _FallbackSplitter()

    fallback_chunks = chunker.split_documents([Document(page_content="plain text body", metadata={"source": "doc-a"})])
    assert fallback_chunks == [
        Document(
            page_content="alpha",
            metadata={
                "source": "doc-a",
                "extra": "doc-a",
                "chunk_strategy": "jsonl_records",
                "start_char": 2,
                "end_char": 7,
                "jsonl_fallback": True,
                "doc_type_kwd": "jsonl",
                "chunk_index": 0,
            },
        )
    ]

    jsonl_text = '{"a":1}\n{"b":2}\n{"c":3}\n'
    record_chunks = chunker.split_documents([Document(page_content=jsonl_text, metadata={"source": "doc-b"})])

    assert [chunk.metadata["chunk_index"] for chunk in record_chunks] == [0, 1, 2]
    assert record_chunks[0].metadata["jsonl_first_index"] == 0
    assert record_chunks[0].metadata["jsonl_last_index"] == 1
    assert record_chunks[1].metadata["jsonl_first_index"] == 1
    assert record_chunks[1].metadata["jsonl_last_index"] == 2
    assert record_chunks[2].metadata["jsonl_first_index"] == 2
    assert record_chunks[2].metadata["jsonl_record_count"] == 1


def test_verify_claim_keeps_default_overlap_mode_supportive_but_blocks_strict_contradictions() -> None:
    from app.rag.core.claim_verifier import verify_claim

    default_mode = verify_claim("Revenue was 10 in 2024", "Revenue was 11 in 2024")
    strict_mode = verify_claim("Revenue was 10 in 2024", "Revenue was 11 in 2024", mode="strict")

    assert default_mode.supported is True
    assert default_mode.diagnostics["contradiction_type"] == "numeric_mismatch"
    assert strict_mode.supported is False
    assert strict_mode.diagnostics["reason_code"] == "contradiction_numeric_mismatch"
    assert strict_mode.diagnostics["numeric_mismatch"] is True


def test_fetch_document_updated_ts_ignores_invalid_ids_and_invalid_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.database as database_module
    import app.models.document as document_module
    from app.rag.core.temporal import fetch_document_updated_ts

    valid_id = uuid4()
    other_id = uuid4()
    rows = [
        (valid_id, None, datetime(2024, 1, 2, tzinfo=timezone.utc)),
        (other_id, datetime(2024, 1, 3, tzinfo=timezone.utc), None),
    ]

    class _Query:
        def __init__(self) -> None:
            self.allowed_ids: set[object] | None = None

        def filter(self, condition):
            if isinstance(condition, tuple) and condition[:2] == ("in", "id"):
                self.allowed_ids = set(condition[2])
            return self

        def all(self):
            if self.allowed_ids is None:
                return rows
            return [row for row in rows if row[0] in self.allowed_ids]

    class _DB:
        def __init__(self) -> None:
            self.query_obj = _Query()

        def query(self, *_args):
            return self.query_obj

        def close(self) -> None:
            raise RuntimeError("close failure")

    class _DocumentModel:
        id = _Field("id")
        updated_at = _Field("updated_at")
        created_at = _Field("created_at")
        tenant_id = _Field("tenant_id")
        dataset_id = _Field("dataset_id")

    monkeypatch.setattr(database_module, "SessionLocal", lambda: _DB())
    monkeypatch.setattr(document_module, "Document", _DocumentModel)

    result = fetch_document_updated_ts(
        [str(valid_id), "not-a-uuid", str(valid_id), str(other_id)],
        tenant_id=uuid4(),
        dataset_id="bad-dataset-id",
        max_docs=1,
    )

    assert result == {str(valid_id): datetime(2024, 1, 2, tzinfo=timezone.utc).timestamp()}


def test_embedding_adapter_embed_documents_mixes_hits_corrupt_entries_and_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.embedding.adapter as adapter_module

    metric_events: list[dict[str, object]] = []

    class _Model:
        dimension = 2

        def encode(self, texts: list[str]) -> list[list[float]]:
            return [[float(index), float(index) + 0.5] for index, _text in enumerate(texts, start=1)]

    class _Pipe:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bytes, int | None]] = []

        def set(self, key: str, payload: bytes, ex: int | None = None) -> None:
            self.calls.append((key, payload, ex))

        def execute(self) -> None:
            return None

    class _Redis:
        def __init__(self) -> None:
            self.pipe = _Pipe()

        def mget(self, _keys):
            return [json.dumps([9.0, 9.5]).encode("utf-8"), b"{bad json", None]

        def pipeline(self, transaction: bool = False) -> _Pipe:
            _ = transaction
            return self.pipe

    redis = _Redis()
    monkeypatch.setattr(adapter_module, "_get_redis_client", lambda: redis)
    monkeypatch.setattr(adapter_module, "_invalidate_redis_client", lambda: None)
    monkeypatch.setattr(adapter_module.settings, "EMBEDDING_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(adapter_module.settings, "EMBEDDING_CACHE_TTL_SEC", 30, raising=False)
    monkeypatch.setattr(adapter_module, "log_metrics", lambda payload: metric_events.append(payload))

    adapter = adapter_module.LangChainEmbeddingsAdapter(_Model(), normalize=False, cache_space_hash="test-space")
    vectors = adapter.embed_documents(["hit", "corrupt", "miss"])

    assert vectors == [[9.0, 9.5], [1.0, 1.5], [2.0, 2.5]]
    assert len(redis.pipe.calls) == 2
    assert metric_events == [
        {
            "event": "embedding.cache",
            "op": "documents",
            "total": 3,
            "hits": 1,
            "misses": 2,
            "corrupt": 1,
        }
    ]


def test_compute_dimensions_prefers_explicit_fusion_evals_and_tracks_abstain_trace_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.evaluation.reports.dashboard_11d as dashboard

    seen_fusion_rows: list[list[dict[str, object]]] = []
    monkeypatch.setattr(dashboard, "compute_routing_accuracy", lambda _rows: {"routing_accuracy": 0.6})
    monkeypatch.setattr(
        dashboard,
        "compute_decomposition_metrics",
        lambda _rows: {"decomposition_f1": 0.7, "exact_match_rate": 0.4},
    )
    monkeypatch.setattr(
        dashboard,
        "compute_fusion_metrics",
        lambda rows: seen_fusion_rows.append(rows) or {"conflict_rate": 0.9, "net_gain_over_best_single": 0.8},
    )

    rows = [
        {
            "sample_id": "s1",
            "query_type": "unanswerable",
            "latency_ms": 100,
            "token_cost": 2,
            "retrieval_trace": {},
            "evaluators": {
                "fusion": {"conflict_rate": 0.2, "net_gain_over_best_single": 0.3},
                "answer_det": {"answer_em": 1.0, "answer_f1": 0.8, "refusal_correct": True},
                "retrieval": {"recall_at_k": 0.9, "mrr": 0.7, "ndcg": 0.8},
                "faithfulness": {"score": 0.95},
            },
        },
        {
            "sample_id": "s2",
            "latency_ms": 200,
            "token_cost": 4,
            "extensions": {"decision_trace": {}},
            "evaluators": {
                "answer_det": {"answer_f1": 0.4, "refusal_correct": False},
                "retrieval": {"recall_at_k": 0.5, "mrr": 0.3, "ndcg": 0.4},
            },
        },
    ]

    dimensions = dashboard._compute_dimensions(rows)

    assert seen_fusion_rows == [[rows[1]]]
    assert dimensions["routing_decision"] == {
        "routing_accuracy": 0.6,
        "decomposition_f1": 0.7,
        "exact_match_rate": 0.4,
    }
    assert dimensions["fusion_quality"] == {
        "conflict_rate": 0.2,
        "net_gain_over_best_single": 0.3,
    }
    assert dimensions["abstain_ability"] == {
        "abstain_rate": 1.0,
        "evaluated_unanswerable": 1,
    }
    assert dimensions["explainability"] == {"decision_trace_coverage": 1.0}


def test_query_variant_stage_applies_latency_budget_to_slow_variants() -> None:
    from app.rag.retrieval.orchestration.query_variants import QueryVariantStageInput, build_query_variant_stage

    output = build_query_variant_stage(
        QueryVariantStageInput(
            query_for_retrieval="main q",
            alias_queries=["alias q"],
            dict_expansions=[],
            kg_query_expansion_queries=[],
            clause_fastlane_queries=[],
            lightweight_subqueries=[],
            multi_queries=["multi query"],
            step_back_used=True,
            step_back_query="step back query",
            sub_questions=["sub question"],
            hyde_used=True,
            hyde_text="hyde content",
            query_expansion_max_queries_raw=None,
            query_expansion_max_candidates_raw=None,
            query_expansion_token_budget_raw=100,
            query_expansion_latency_budget_ms_raw=10,
            query_expansion_elapsed_ms=25,
        )
    )

    assert output.retrieval_queries == [
        ("main", "main q"),
        ("alias", "alias q"),
    ]
    assert output.query_expansion_budget_meta == {
        "enabled": True,
        "max_queries": 0,
        "max_candidates": 0,
        "token_budget": 100,
        "latency_budget_ms": 10.0,
        "generation_elapsed_ms": 25.0,
        "candidate_count": 5,
        "selected_count": 1,
        "selected_tokens": 2,
        "dropped_count": 4,
        "degraded": True,
        "reasons": [
            "latency_budget_exceeded",
            "latency_budget_drop:mq",
            "latency_budget_drop:step_back",
            "latency_budget_drop:subq",
            "latency_budget_drop:hyde",
        ],
    }
