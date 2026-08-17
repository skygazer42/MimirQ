import asyncio
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from app.models.document import Document as DBDocument
from app.models.document import DocumentParsedContent


class _StaticQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def options(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _ModelDB:
    def __init__(self, rows_by_model):
        self._rows_by_model = dict(rows_by_model)

    def query(self, model):
        return _StaticQuery(self._rows_by_model.get(model))


class _RollbackDB:
    def __init__(self) -> None:
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True


class _RagConfig:
    top_k = 4
    score_threshold = 0.25
    retrieval_mode = "hybrid"
    retrieval_profile = "balanced"
    retrieval_contract_mode = "best_effort"
    must_recall = False
    must_recall_expected_source_keys = ["policy"]
    must_recall_required_anchor_fields = []
    intent_router = None
    intent_router_policy = None
    industry_rules_enabled = False
    industry_rules_rulesets = []
    enable_query_alias_expansion = False
    query_aliases = []
    query_alias_max_queries = 0
    enable_multi_query = False
    multi_query_count = 0
    multi_query_temperature = 0.0
    multi_query_max_chars = 0
    enable_hyde = False
    enable_query_decomposition = False
    enable_hierarchy_recall = False
    hierarchy_family_collapse = False
    hierarchy_family_aggregation = False
    hierarchy_tree_dedup = False
    hierarchy_parent_depth = 0
    hierarchy_sibling_window = 0
    hierarchy_overfetch_factor = 0.0
    enable_kg_query_expansion = False
    enable_kg_chunk_injection = False
    kg_chunk_injection_max_chunks = 0
    enable_kg_chunk_boost = False
    kg_chunk_boost_weight = 0.0
    kg_chunk_boost_max_promoted = 0
    alpha = 0.5
    fusion_strategy = "rrf"
    fusion_budgets = {}
    fusion_min_scores = {}
    fusion_weights = {}
    enable_weight_rerank = False
    vector_weight = 0.0
    keyword_weight = 0.0
    mmr_lambda = 0.0
    enable_reranker = False
    reranker_provider = None
    reranker_top_n = 0
    sparse_retrieval_enabled = False
    sparse_retrieval_provider = None
    metadata_filter = None
    max_tokens = 512
    visible_evidence_only = False

    def __getattr__(self, _name: str):
        return None


class _ConnectorRunQuery:
    def __init__(self, run):
        self._run = run

    def options(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._run


class _ConnectorRunDB:
    def __init__(self, run):
        self._run = run
        self.closed = False
        self.commit_calls = 0
        self.refreshed = []

    def query(self, model):
        return _ConnectorRunQuery(self._run)

    def commit(self) -> None:
        self.commit_calls += 1

    def refresh(self, obj) -> None:
        self.refreshed.append(obj)

    def close(self) -> None:
        self.closed = True


def test_plan_connector_reconcile_applies_stale_disable_and_reenable() -> None:
    from app.services.connector_reconcile_service import plan_connector_reconcile

    now = datetime(2026, 8, 16, 9, 30, tzinfo=UTC)
    active_stale = SimpleNamespace(
        disabled_at=None,
        doc_metadata={"connector": {"connector_id": "drive_files", "config_id": "cfg-1", "source_ref": "stale-ref"}},
    )
    active_kept = SimpleNamespace(
        disabled_at=None,
        doc_metadata={"connector": {"connector_id": "drive_files", "config_id": "cfg-1", "source_ref": "keep-ref"}},
    )
    disabled_match = SimpleNamespace(
        disabled_at=now,
        doc_metadata={"connector": {"connector_id": "drive_files", "config_id": "cfg-1", "source_ref": "reenable-ref"}},
    )
    missing_identity = SimpleNamespace(
        disabled_at=None,
        doc_metadata={"connector": {"connector_id": "drive_files", "source_ref": "ignored-ref"}},
    )

    report = plan_connector_reconcile(
        connector_id="drive_files",
        config_id="cfg-1",
        dataset_id="dataset-1",
        documents=[active_stale, active_kept, disabled_match, missing_identity],
        desired_source_refs=["keep-ref", "reenable-ref", "missing-ref"],
        apply=True,
        now=now,
        sample_limit=2,
    )

    assert active_stale.disabled_at == now
    assert active_kept.disabled_at is None
    assert disabled_match.disabled_at is None
    assert report["documents_scanned"] == 4
    assert report["documents_considered"] == 4
    assert report["documents_without_identity"] == 1
    assert report["stale_source_refs"] == 1
    assert report["reenable_source_refs"] == 1
    assert report["missing_source_refs"] == 1
    assert report["stale_source_refs_sample"] == ["stale-ref"]
    assert report["reenable_source_refs_sample"] == ["reenable-ref"]
    assert report["missing_source_refs_sample"] == ["missing-ref"]
    assert report["disabled_documents"] == 1
    assert report["reenabled_documents"] == 1


def test_parse_qa_faq_import_bytes_csv_normalizes_payload() -> None:
    from app.services.evidence_item_import import parse_qa_faq_import_bytes

    raw = (
        "Question,Expected Answer,Tags,source,extra\n"
        "\"  How  to deploy?  \",Done,\"alpha; beta;alpha\",guide,keep\n"
        ",Missing query,,guide,\n"
    ).encode("utf-8")

    items, errors = parse_qa_faq_import_bytes(raw=raw, filename="faq.csv")

    assert items == [
        {
            "query": "How to deploy?",
            "expected_answer": None,
            "tags": ["alpha", "beta"],
            "source_metadata": {"source": "guide", "Expected Answer": "Done", "extra": "keep"},
        }
    ]
    assert errors == [{"index": 1, "error": "query is required"}]


def test_parse_qa_faq_import_bytes_jsonl_reports_line_errors() -> None:
    from app.services.evidence_item_import import parse_qa_faq_import_bytes

    raw = b'{"question":"First","tags":["a"]}\nnot json\n{"question":"   "}\n'

    items, errors = parse_qa_faq_import_bytes(raw=raw, filename="faq.jsonl")

    assert items == [
        {
            "query": "First",
            "expected_answer": None,
            "tags": ["a"],
            "source_metadata": {},
        }
    ]
    assert errors == [
        {"line": 2, "error": "invalid JSON"},
        {"line": 3, "error": "query is required"},
    ]


def test_get_document_parsed_content_uses_text_fallback_and_metadata(monkeypatch) -> None:
    from app.api.v1 import document_content

    tenant_id = uuid4()
    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        file_type="txt",
        filename="note.txt",
        file_path=str(Path("/tmp/note.txt")),
        doc_metadata={
            "parsed_content_persisted": {"source": "persisted"},
            "parser_backend": "plain_text",
            "elements": 3,
        },
    )
    db = _ModelDB(
        {
            DBDocument: document,
            DocumentParsedContent: None,
        }
    )

    monkeypatch.setattr(document_content.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(document_content, "assert_document_acl_readable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        document_content,
        "_read_local_text_source_fallback",
        lambda *_args, **_kwargs: ("fallback text", True),
    )

    response = document_content.get_document_parsed_content(
        document_id=document_id,
        max_chars=12,
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert response.document_id == document_id
    assert response.available is True
    assert response.markdown_content == "fallback text"
    assert response.original_markdown_content == "fallback text"
    assert response.markdown_truncated is True
    assert response.original_markdown_truncated is True
    assert response.persisted_meta == {
        "source": "persisted",
        "parser_backend": "plain_text",
        "elements": 3,
    }
    assert response.max_chars == 12


def test_list_queryset_health_runs_filters_newest_first_and_timeseries(monkeypatch) -> None:
    from app.api.v1 import observability

    history = [
        {
            "generated_at": "2026-08-15T10:00:00Z",
            "profile_hash": "keep",
            "metrics": {"hit_at_k": 0.5, "mrr": 0.25, "ndcg_at_k": 0.75, "p95_latency_ms": 150},
            "risk": {"miss_rate": 0.1, "weak_hit_rate": 0.2},
            "status": "ok",
        },
        {
            "generated_at": "2026-08-15T11:00:00Z",
            "profile_hash": "skip",
            "metrics": {"hit_at_k": 0.1},
            "risk": {},
            "status": "warn",
        },
        {
            "generated_at": "2026-08-15T12:00:00Z",
            "profile_hash": "keep",
            "metrics": {"hit_at_k": 0.8, "mrr": None, "ndcg_at_k": 0.9, "p95_latency_ms": 99},
            "risk": {"miss_rate": 0.0, "weak_hit_rate": 0.05},
            "status": "pass",
        },
    ]
    module = types.ModuleType("app.services.queryset_health_service")
    module.load_queryset_health_history = lambda _path: list(history)

    monkeypatch.setattr(observability, "_ensure_admin", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(observability.settings, "QUERYSET_HEALTH_HISTORY_PATH", "/tmp/queryset-history.jsonl", raising=False)
    monkeypatch.setitem(sys.modules, "app.services.queryset_health_service", module)

    response = observability.list_queryset_health_runs(
        limit=5,
        profile_hash="keep",
        tenant_id=uuid4(),
        account_id="admin",
        db=object(),
    )

    assert response.enabled is False
    assert response.path == "/tmp/queryset-history.jsonl"
    assert response.total == 2
    assert response.truncated is False
    assert [item["generated_at"] for item in response.items] == [
        "2026-08-15T12:00:00Z",
        "2026-08-15T10:00:00Z",
    ]
    assert response.timeseries["status"] == ["ok", "pass"]
    assert response.timeseries["hit_at_k"] == [0.5, 0.8]
    assert response.timeseries["miss_rate"] == [0.1, 0.0]
    assert response.timeseries["ts_ms"] == [
        int(datetime(2026, 8, 15, 10, 0, tzinfo=UTC).timestamp() * 1000),
        int(datetime(2026, 8, 15, 12, 0, tzinfo=UTC).timestamp() * 1000),
    ]


def test_execute_graph_chat_once_collects_multimodal_state_and_structured_metrics(monkeypatch) -> None:
    from app.services import chat_execution_runtime

    captured = {}

    def fake_build_rag_state(**kwargs):
        captured["state_input"] = kwargs
        return {"db": kwargs["db"], "seed": "ok"}

    class _FakeWorkflow:
        def invoke(self, state, config=None, context=None):
            captured["invoke_state"] = state
            captured["invoke_config"] = config
            captured["invoke_context"] = context
            return {
                "answer": '{"result":"graph"}',
                "citations": [{"document_name": "Policy", "chunk_content": "Evidence body"}],
                "metrics": {"graph": True},
            }

    def fake_tag_docs(
        _db,
        *,
        tenant_id,
        document_ids,
        question,
        must_recall_expected_source_keys=None,
    ):
        captured["tag_kwargs"] = {
            "tenant_id": tenant_id,
            "document_ids": document_ids,
            "question": question,
            "must_recall_expected_source_keys": must_recall_expected_source_keys,
        }
        return ([{"kind": "tag"}], {"enabled": True, "used": True, "reason": "matched"})

    def fake_image_docs(_db, **kwargs):
        captured["image_kwargs"] = kwargs
        return ([{"kind": "image"}], {"enabled": True, "used": True, "reason": "matched"})

    monkeypatch.setitem(
        sys.modules,
        "app.rag.core.text",
        types.SimpleNamespace(
            parse_json_from_text=lambda text, expected: (
                {"parsed": text},
                {"ok": True, "method": "json", "error": None},
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.rag.pipelines.langgraph",
        types.SimpleNamespace(build_rag_state=fake_build_rag_state, rag_workflow=_FakeWorkflow()),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.rag.policy.modality_router",
        types.SimpleNamespace(classify_query_modality=lambda _message: ("image", ["contains image cue"])),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.chat_tag_service",
        types.SimpleNamespace(build_chat_tag_context_docs=fake_tag_docs),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.chat_image_service",
        types.SimpleNamespace(build_chat_image_context_docs=fake_image_docs),
    )
    monkeypatch.setattr(chat_execution_runtime, "_source_identification_answer_from_citations", lambda **_kwargs: None)
    monkeypatch.setattr(chat_execution_runtime.settings, "LANGGRAPH_RECURSION_LIMIT", 17, raising=False)

    db = _RollbackDB()
    tenant_id = uuid4()
    dataset_id = uuid4()
    request = SimpleNamespace(
        message="Show the image policy",
        structured_output=True,
        structured_preset="json_object",
    )
    context = chat_execution_runtime.ChatExecutionContext(
        db=db,
        tenant_id=tenant_id,
        account_id="acct-1",
        request=request,
        conversation_id=uuid4(),
        request_id="req-graph-1",
        doc_ids_to_use=[uuid4()],
        history_for_llm=[{"role": "user", "content": "prior"}],
        scope_dataset_id=dataset_id,
        dataset_id_used=None,
        effective_rag_config=_RagConfig(),
        effective_prompt_template_id=None,
        effective_prompt_template_key="prompt-key",
        effective_prompt_ab_experiment_key="ab-key",
        rag_config_template_meta={"template": "balanced"},
    )

    result = chat_execution_runtime.execute_graph_chat_once(context=context)

    assert db.rolled_back is True
    assert result.content == '{"result":"graph"}'
    assert result.citations == [{"document_name": "Policy", "chunk_content": "Evidence body"}]
    assert result.structured_data == {"parsed": '{"result":"graph"}'}
    assert result.metrics["graph"] is True
    assert result.metrics["source_identification_answer_used"] is False
    assert result.metrics["structured_parse_ok"] is True
    assert result.metrics["structured_parse_method"] == "json"
    assert result.metrics["structured_type"] == "dict"
    assert result.metrics["structured_preset"] == "json_object"
    assert result.metrics["multimodal_router"]["modality"] == "image"
    assert result.metrics["tag"]["used"] is True
    assert result.metrics["image"]["used"] is True
    assert captured["tag_kwargs"]["must_recall_expected_source_keys"] == ["policy"]
    assert captured["image_kwargs"]["dataset_id"] == dataset_id
    assert "db" not in captured["invoke_state"]
    assert captured["invoke_state"]["tag_docs"] == [{"kind": "tag"}, {"kind": "image"}]
    assert captured["invoke_state"]["rag_config_template"] == {"template": "balanced"}
    assert captured["invoke_config"]["recursion_limit"] == 17
    assert captured["invoke_context"]["tenant_id"] == str(tenant_id)


def test_execute_confluence_space_run_probes_completion_before_soft_delete(monkeypatch) -> None:
    from app.api.v1 import connectors_confluence

    tenant_id = uuid4()
    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        status="queued",
        started_at=None,
        error_message="old",
        stats={},
        config={},
        dataset_id=uuid4(),
        documents=[],
    )
    db = _ConnectorRunDB(run)
    calls = {"probe": 0, "soft_delete": 0, "finalize": None}

    async def fake_fetch_listing_page(_pool, *, settings_map, start):
        assert settings_map["max_pages"] == 2
        assert start == 0
        return [{"id": "page-1"}, {"id": "page-2"}], "https://example.atlassian.net"

    async def fake_process_batch(_pool, _db, **kwargs):
        assert kwargs["run_id"] == run_id
        return {"processed": 2, "observed_page_ids": {"page-1", "page-2"}}

    async def fake_probe_listing_complete(_pool, *, settings_map, start):
        calls["probe"] += 1
        assert settings_map["soft_delete"] is True
        assert start == 2
        return True

    def fake_soft_delete_missing_pages(_db, **kwargs):
        calls["soft_delete"] += 1
        assert kwargs["observed_page_ids"] == {"page-1", "page-2"}
        return 7

    def fake_finalize_success(_db, **kwargs):
        calls["finalize"] = kwargs

    helpers = {
        "SessionLocal": lambda: db,
        "_now": lambda: datetime(2026, 8, 16, 10, 0, tzinfo=UTC),
        "decrypt_connector_config_secrets": lambda cfg: cfg,
        "_finalize_connector_stats": lambda stats: stats,
        "get_http_client_pool": lambda: object(),
        "_process_confluence_space_page_batch": fake_process_batch,
        "_probe_confluence_space_listing_complete": fake_probe_listing_complete,
        "_soft_delete_missing_confluence_pages": fake_soft_delete_missing_pages,
        "_finalize_confluence_space_run_success": fake_finalize_success,
        "_mark_confluence_space_run_failed": lambda *_args, **_kwargs: pytest.fail("run should not fail"),
        "_finalize_cancelled_confluence_space_run": lambda *_args, **_kwargs: pytest.fail("run should not cancel"),
    }

    monkeypatch.setattr(connectors_confluence, "_resolve_connectors_helper", lambda name: helpers[name])
    monkeypatch.setattr(
        connectors_confluence,
        "_build_confluence_space_run_settings",
        lambda _config: {
            "space_key": "ENG",
            "effective_mode": "full",
            "cursor_last_modified": "",
            "max_pages": 2,
            "page_size": 2,
            "soft_delete": True,
        },
    )
    monkeypatch.setattr(connectors_confluence, "_build_confluence_space_search_cql", lambda **_kwargs: "type=page")
    monkeypatch.setattr(connectors_confluence, "_initialize_confluence_space_run_stats", lambda **_kwargs: {"seed": True})
    monkeypatch.setattr(connectors_confluence, "_initialize_confluence_space_progress", lambda: {"processed": 0})
    monkeypatch.setattr(connectors_confluence, "_fetch_confluence_space_listing_page", fake_fetch_listing_page)
    monkeypatch.setattr(connectors_confluence, "_confluence_space_run_cancelled", lambda *_args, **_kwargs: False)

    asyncio.run(
        connectors_confluence._execute_confluence_space_run(
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by="owner",
        )
    )

    assert run.status == "running"
    assert run.error_message is None
    assert calls["probe"] == 1
    assert calls["soft_delete"] == 1
    assert calls["finalize"]["soft_deleted"] == 7
    assert calls["finalize"]["progress"]["observed_page_ids"] == {"page-1", "page-2"}
    assert db.closed is True


def test_merge_small_chunks_preview_merges_with_previous_and_keeps_page_boundaries() -> None:
    from app.services.document_preview_utils import _merge_small_chunks_preview

    documents = [
        Document(page_content="abcdefgh", metadata={"page_index": 1}),
        Document(page_content="ijklmnop", metadata={"page_index": 2}),
    ]
    chunks = [
        Document(page_content="abcde", metadata={"page_index": 1, "start_char": 0, "end_char": 5}),
        Document(page_content="fg", metadata={"page_index": 1, "start_char": 5, "end_char": 7}),
        Document(page_content="ij", metadata={"page_index": 2, "start_char": 0, "end_char": 2}),
    ]

    merged = _merge_small_chunks_preview(documents=documents, chunks=chunks, min_chars=4)

    assert [chunk.page_content for chunk in merged] == ["abcdefg", "ij"]
    assert merged[0].metadata["start_char"] == 0
    assert merged[0].metadata["end_char"] == 7
    assert merged[0].metadata["merged_small_chunks"] == 1
    assert merged[1].metadata["page_index"] == 2
