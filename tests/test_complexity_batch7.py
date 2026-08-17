from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from langchain_core.documents import Document

from app.api.v1 import ingestion_runs
from app.rag.chunking.strategies.markdown_hierarchy import MarkdownHierarchyChunker
from app.rag.chunking.strategies.recursive import LangChainRecursiveChunker
from app.rag.chunking.strategies.subtitles import SubtitlesChunker
from app.rag.evaluation.datasets.validator import validate_eval_dataset
from app.rag.evaluation.parse_bench import build_doc_type_matrix
from app.rag.policy.intent_router_model import (
    INTENT_ROUTER_MODEL_SCHEMA_V1,
    normalize_intent_router_model,
)
from app.rag.preprocessing.images import strip_images
from app.rag.retrieval.orchestration.query_contract import (
    HierarchyContractSettings,
    QueryContractDefaults,
    QueryContractNormalizationInput,
    normalize_query_contract,
)
from app.services.evidence_drift_audit import (
    DRIFT_REASON_CHUNK_DOCUMENT_MISMATCH,
    DRIFT_REASON_DOCUMENT_DATASET_MISMATCH,
    classify_reference_source_drift,
)


def _query_contract_defaults() -> QueryContractDefaults:
    return QueryContractDefaults(
        retrieval_top_k=5,
        similarity_threshold=0.25,
        enable_reranker=False,
        reranker_provider="cross_encoder",
        reranker_top_n=8,
        retrieval_contract_mode="",
        hard_fallback_enabled_setting=False,
        hard_fallback_mode_setting="keyword",
        hard_fallback_top_k_setting=30,
        visible_evidence_only_setting=False,
        evidence_span_strict_setting=False,
        retrieval_fusion_strategy="rrf",
        retrieval_mmr_lambda=0.3,
    )


def _query_contract_hierarchy() -> HierarchyContractSettings:
    return HierarchyContractSettings(
        enabled=False,
        family_collapse=False,
        family_aggregation="separate",
        tree_dedup=False,
        parent_depth=0,
        sibling_window=0,
        overfetch_factor=1,
    )


def test_build_doc_type_matrix_aggregates_numeric_attempt_metrics() -> None:
    report = {
        "cases": [
            {
                "id": "sales_table_case",
                "file_type": "pdf",
                "attempts": [
                    {
                        "backend": "Basic",
                        "ok": True,
                        "golden_similarity": 0.81,
                        "golden_coverage_ratio": 0.51,
                        "table_continuity_recall": 0.9,
                        "table_grits": {"f1": 0.6, "topology": 0.5, "content": 0.4},
                    },
                    {
                        "backend": "Basic",
                        "ok": False,
                        "golden_similarity": 0.61,
                        "golden_coverage_ratio": 0.71,
                        "table_continuity_recall": 0.7,
                        "table_grits": {"f1": 0.2, "topology": 0.1, "content": 0.3},
                    },
                ],
            },
            {
                "id": "diagram_case",
                "file_type": "md",
                "attempts": [
                    {
                        "backend": "Vision",
                        "ok": True,
                        "golden_similarity": 0.9,
                        "golden_coverage_ratio": 0.8,
                    }
                ],
            },
            "ignore-me",
        ]
    }

    matrix = build_doc_type_matrix(report)

    assert matrix == {
        "basic": {
            "table": {
                "cases": 2,
                "ok_rate": 0.5,
                "text_edit_similarity_mean": 0.71,
                "text_coverage_mean": 0.61,
                "table_grits_f1_mean": 0.4,
                "table_grits_topology_mean": 0.3,
                "table_grits_content_mean": 0.35,
                "table_continuity_mean": 0.8,
            }
        },
        "vision": {
            "diagram": {
                "cases": 1,
                "ok_rate": 1.0,
                "text_edit_similarity_mean": 0.9,
                "text_coverage_mean": 0.8,
                "table_grits_f1_mean": None,
                "table_grits_topology_mean": None,
                "table_grits_content_mean": None,
                "table_continuity_mean": None,
            }
        },
    }


def test_normalize_intent_router_model_filters_and_clamps_rules() -> None:
    model = normalize_intent_router_model(
        {
            "schema": INTENT_ROUTER_MODEL_SCHEMA_V1,
            "version": 0,
            "rules": [
                {
                    "rule_id": "primary-rule",
                    "tokens": ["Alpha", "alpha", "beta", "", "beta"],
                    "overrides": {"top_k": 7, "score_threshold": 0.3, "ignored": True},
                    "min_match": "9",
                    "confidence": "1.7",
                    "weight": "-2",
                },
                {"rule_id": "", "tokens": ["skip"], "overrides": {"top_k": 5}},
            ],
        }
    )

    assert model == {
        "schema": INTENT_ROUTER_MODEL_SCHEMA_V1,
        "version": 1,
        "rules": [
            {
                "rule_id": "primary-rule",
                "tokens": ["Alpha", "beta"],
                "min_match": 2,
                "confidence": 1.0,
                "weight": 0.0,
                "overrides": {"top_k": 7, "score_threshold": 0.3},
            }
        ],
    }


def test_strip_images_preserves_code_fences_and_non_decorative_images() -> None:
    text = "\n".join(
        [
            "keep ![chart](figures/chart.png)",
            "drop ![logo](logo.png)",
            "drop-ref ![二维码][qr-code]",
            '<img src="banner.png" alt="Banner">',
            "```md",
            "![logo](inside-code.png)",
            "```",
        ]
    )

    result = strip_images(text, mode="decorative")

    assert result.removed == 3
    assert result.changed is True
    assert "![chart](figures/chart.png)" in result.text
    assert "![logo](logo.png)" not in result.text
    assert "![二维码][qr-code]" not in result.text
    assert '<img src="banner.png" alt="Banner">' not in result.text
    assert "![logo](inside-code.png)" in result.text


def test_normalize_query_contract_routes_auto_mode_and_applies_strict_profile() -> None:
    payload = QueryContractNormalizationInput(
        state={
            "retrieval_mode": "auto",
            "retrieval_profile": "grounded_strict",
            "top_k": 3,
            "reranker_provider": "custom-reranker",
        },
        query_for_retrieval="列举差异",
        requested_retrieval_mode=None,
        requested_retrieval_profile=None,
        sparse_enabled=False,
        sparse_provider="bm25",
        hierarchy=_query_contract_hierarchy(),
        defaults=_query_contract_defaults(),
    )

    result = normalize_query_contract(payload)

    assert result.request_retrieval_mode == "mmr"
    assert result.retrieval_mode_routed is True
    assert result.profile_norm == "grounded_strict"
    assert result.retriever_update["retrieval_mode"] == "hybrid"
    assert result.retriever_update["reranker_provider"] == "custom-reranker"
    assert result.retriever_update["k"] == 20
    assert result.state_updates == {
        "retrieval_contract_mode": "evidence_strict",
        "visible_evidence_only": True,
    }
    assert result.retrieval_contract_mode == "evidence_strict"
    assert result.retrieval_contract_policy["force_visible_evidence_only"] is True
    assert result.contract_deterministic_recall is False


def test_normalize_query_contract_disables_dedup_for_recall_first_profiles() -> None:
    payload = QueryContractNormalizationInput(
        state={
            "retrieval_mode": "vector",
            "retrieval_profile": "recall20",
            "top_k": 12,
        },
        query_for_retrieval="status code",
        requested_retrieval_mode=None,
        requested_retrieval_profile=None,
        sparse_enabled=True,
        sparse_provider="splade",
        hierarchy=_query_contract_hierarchy(),
        defaults=_query_contract_defaults(),
    )

    result = normalize_query_contract(payload)

    assert result.profile_norm == "recall20"
    assert result.retriever_update["k"] == 20
    assert result.retriever_update["dedup_enabled"] is False
    assert result.retriever_update["max_chunks_per_doc"] == 0
    assert result.retriever_update["max_chunks_per_page"] == 0
    assert result.retriever_update["min_distinct_docs"] == 0


@pytest.mark.parametrize(
    ("document_row", "chunk_row", "suite_dataset_id", "reason"),
    [
        (
            {"dataset_id": uuid4()},
            {"document_id": uuid4(), "chunk_index": 1, "metadata": {}},
            uuid4(),
            DRIFT_REASON_DOCUMENT_DATASET_MISMATCH,
        ),
        (
            {"dataset_id": None},
            {"document_id": uuid4(), "chunk_index": 1, "metadata": {}},
            None,
            DRIFT_REASON_CHUNK_DOCUMENT_MISMATCH,
        ),
    ],
)
def test_classify_reference_source_drift_reports_expected_reason_precedence(
    document_row: dict[str, object],
    chunk_row: dict[str, object],
    suite_dataset_id,
    reason: str,
) -> None:
    document_id = uuid4()
    reference_source = {
        "document_id": str(document_id),
        "chunk_id": str(uuid4()),
        "chunk_index": 1,
        "pipeline_hash": "pipe-1",
        "doc_pipeline_key": "doc-pipe-1",
    }

    ok, actual_reason, expected, observed = classify_reference_source_drift(
        reference_source=reference_source,
        document_row=document_row,
        chunk_row=chunk_row,
        suite_dataset_id=suite_dataset_id,
    )

    assert ok is False
    assert actual_reason == reason
    assert expected["document_id"] == str(document_id)
    assert expected["chunk_index"] == 1
    if reason == DRIFT_REASON_DOCUMENT_DATASET_MISMATCH:
        assert observed["suite_dataset_id"] == str(suite_dataset_id)
    else:
        assert observed["chunk_document_id"] == str(chunk_row["document_id"])


def test_replay_ingestion_run_creates_new_run_and_schedules_background_work(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    base_run_id = uuid4()
    new_run_id = uuid4()
    doc_ids = [uuid4(), uuid4()]
    base_run = SimpleNamespace(
        id=base_run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        kind="upload",
        requested_by="acct-1",
        status="completed",
        config={},
        stats={},
        error_message=None,
        created_at=None,
        started_at=None,
        finished_at=None,
        documents=[SimpleNamespace(document_id=doc_ids[0]), SimpleNamespace(document_id=doc_ids[1])],
    )
    new_run = SimpleNamespace(
        id=new_run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        kind="replay",
        requested_by="acct-1",
        status="pending",
        config={"replay_of": str(base_run_id), "base_kind": "upload"},
        stats={},
        error_message=None,
        created_at=None,
        started_at=None,
        finished_at=None,
        documents=[],
    )

    class _Query:
        def __init__(self, result):
            self._result = result

        def options(self, *_args, **_kwargs):
            return self

        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return self._result

    class _DB:
        def __init__(self, result):
            self._result = result
            self.commits = 0
            self.rollbacks = 0

        def query(self, _model):
            return _Query(self._result)

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    db = _DB(base_run)
    add_calls: list[dict[str, object]] = []

    monkeypatch.setattr(ingestion_runs.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(ingestion_runs.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(ingestion_runs.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        ingestion_runs,
        "audit_log_event",
        lambda *_a, **_k: None,
        raising=True,
    )
    monkeypatch.setattr(
        ingestion_runs.IngestionRunService,
        "create_run",
        lambda *_a, **_k: new_run,
        raising=True,
    )

    def _add_document(*_args, **kwargs):
        add_calls.append(kwargs)

    monkeypatch.setattr(ingestion_runs.IngestionRunService, "add_document", _add_document, raising=True)

    background_tasks = BackgroundTasks()
    result = ingestion_runs.replay_ingestion_run(
        base_run_id,
        background_tasks,
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert result.id == new_run_id
    assert result.kind == "replay"
    assert result.config == {"replay_of": str(base_run_id), "base_kind": "upload"}
    assert [call["document_id"] for call in add_calls] == doc_ids
    assert all(call["initial_status"] == "pending" for call in add_calls)
    assert db.commits == 1
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].kwargs == {
        "tenant_id": tenant_id,
        "account_id": "acct-1",
        "new_run_id": new_run_id,
        "doc_ids": [doc_ids[0], doc_ids[1]],
    }


def test_replay_ingestion_run_rejects_runs_without_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    base_run = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, dataset_id=None, documents=[])

    class _Query:
        def options(self, *_args, **_kwargs):
            return self

        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return base_run

    class _DB:
        def query(self, _model):
            return _Query()

    monkeypatch.setattr(ingestion_runs.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    with pytest.raises(HTTPException, match="No documents to replay") as exc_info:
        ingestion_runs.replay_ingestion_run(
            base_run.id,
            BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="acct-1",
            db=_DB(),
        )

    assert exc_info.value.status_code == 400


def test_markdown_hierarchy_chunker_preserves_order_offsets_and_heading_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "# Title\n\nAlpha one. Alpha two.\n\n## Details\n\nBeta one.\n"
    alpha_start = text.index("Alpha")
    beta_start = text.index("Beta")
    monkeypatch.setattr(
        "app.rag.chunking.strategies.markdown_hierarchy.hierarchical_chunk_markdown",
        lambda _text: {
            "paragraphs": [
                {
                    "id": "p1",
                    "text": "Alpha one. Alpha two.\n",
                    "start": alpha_start,
                    "end": alpha_start + len("Alpha one. Alpha two.\n"),
                    "hierarchy_basis": "markdown",
                    "hierarchy_level": "paragraph",
                    "hierarchy_node_key": "p1",
                    "hierarchy_family_key": "p1",
                    "hierarchy_parent_key": None,
                    "hierarchy_prev_sibling_key": None,
                    "hierarchy_next_sibling_key": "p2",
                    "hierarchy_sibling_index": 0,
                    "tokens_est": 5,
                },
                {
                    "id": "p2",
                    "text": "Beta one.\n",
                    "start": beta_start,
                    "end": beta_start + len("Beta one.\n"),
                    "hierarchy_basis": "markdown",
                    "hierarchy_level": "paragraph",
                    "hierarchy_node_key": "p2",
                    "hierarchy_family_key": "p2",
                    "hierarchy_parent_key": None,
                    "hierarchy_prev_sibling_key": "p1",
                    "hierarchy_next_sibling_key": None,
                    "hierarchy_sibling_index": 1,
                    "tokens_est": 2,
                },
            ],
            "sentences": [
                {
                    "id": "s1",
                    "parent_id": "p1",
                    "text": "Alpha one.",
                    "start": alpha_start,
                    "end": alpha_start + len("Alpha one."),
                    "hierarchy_basis": "markdown",
                    "hierarchy_level": "sentence",
                    "hierarchy_node_key": "s1",
                    "hierarchy_family_key": "p1",
                    "hierarchy_parent_key": "p1",
                    "hierarchy_prev_sibling_key": None,
                    "hierarchy_next_sibling_key": "s2",
                    "hierarchy_sibling_index": 0,
                    "tokens_est": 2,
                    "index": 1,
                },
                {
                    "id": "s2",
                    "parent_id": "p1",
                    "text": "Alpha two.",
                    "start": alpha_start + len("Alpha one. "),
                    "end": alpha_start + len("Alpha one. Alpha two."),
                    "hierarchy_basis": "markdown",
                    "hierarchy_level": "sentence",
                    "hierarchy_node_key": "s2",
                    "hierarchy_family_key": "p1",
                    "hierarchy_parent_key": "p1",
                    "hierarchy_prev_sibling_key": "s1",
                    "hierarchy_next_sibling_key": None,
                    "hierarchy_sibling_index": 1,
                    "tokens_est": 2,
                    "index": 2,
                },
            ],
        },
        raising=True,
    )

    chunker = MarkdownHierarchyChunker(chunk_size=200, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"doc_id": "doc-1"})])

    assert [chunk.page_content for chunk in chunks] == [
        "Alpha one. Alpha two.\n",
        "Alpha one.",
        "Alpha two.",
        "Beta one.\n",
    ]
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == [0, 1, 2, 3]
    assert chunks[0].metadata["header_path"] == "Title"
    assert chunks[1].metadata["parent_id"] == "p1"
    assert chunks[3].metadata["header_path"] == "Title > Details"


def test_recursive_chunker_keeps_tables_atomic_and_offsets_absolute() -> None:
    text = "Alpha<table><tr><td>x</td></tr></table>Omega"
    table_text = "<table><tr><td>x</td></tr></table>"
    table_start = text.index(table_text)
    table_end = table_start + len(table_text)
    chunker = LangChainRecursiveChunker(chunk_size=10, chunk_overlap=0)

    class _FakeSplitter:
        def create_documents(self, *, texts, metadatas):
            source = texts[0]
            meta = dict(metadatas[0] or {})
            if source == "Alpha":
                return [Document(page_content="Alpha", metadata={**meta, "start_index": 0})]
            if source == "Omega":
                return [Document(page_content="Omega", metadata={**meta, "start_index": 0})]
            raise AssertionError(source)

    chunker.splitter = _FakeSplitter()
    chunks = chunker.split_documents([Document(page_content=text, metadata={"doc_id": "doc-1"})])

    assert [chunk.page_content for chunk in chunks] == ["Alpha", table_text, "Omega"]
    assert chunks[0].metadata["start_char"] == 0
    assert chunks[0].metadata["end_char"] == 5
    assert chunks[1].metadata["start_char"] == table_start
    assert chunks[1].metadata["end_char"] == table_end
    assert chunks[1].metadata["doc_type_kwd"] == "table"
    assert chunks[2].metadata["start_char"] == table_end
    assert chunks[2].metadata["end_char"] == len(text)


def test_subtitles_chunker_emits_prefix_and_cue_chunks_in_order() -> None:
    text = (
        "WEBVTT\n\n"
        "1\n00:00:01.000 --> 00:00:02.000\nHello\n\n"
        "2\n00:00:03.000 --> 00:00:04.000\nWorld\n\n"
        "3\n00:00:05.000 --> 00:00:06.000\nAgain\n"
    )

    chunker = SubtitlesChunker(chunk_size=10, chunk_overlap=0)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"doc_id": "doc-1"})])

    assert chunks[0].page_content == "WEBVTT"
    assert chunks[0].metadata["cue_start_index"] == -1
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[0].metadata["start_char"] == 0
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == [0, 1, 2, 3]
    assert [chunk.metadata["cue_count"] for chunk in chunks[1:]] == [1, 1, 1]
    assert chunks[1].metadata["first_timecode"] == "00:00:01.000"
    assert chunks[3].metadata["last_timecode"] == "00:00:06.000"
    assert chunks[1].metadata["start_char"] < chunks[2].metadata["start_char"] < chunks[3].metadata["start_char"]


def test_validate_eval_dataset_preserves_error_messages_and_row_normalization() -> None:
    rows = [
        {
            "sample_id": "dup",
            "query": "",
            "query_type": "bad",
            "source_type": "bad",
            "annotation_status": "bad",
            "review_status": "bad",
        },
        {
            "sample_id": "dup",
            "query": "What changed?",
            "query_type": "structured",
            "source_type": "synthetic",
            "annotation_status": "todo",
            "review_status": "pending",
        },
    ]
    manifest = {
        "schema_version": "bad-schema",
        "sample_count": 1,
        "query_type_counts": {"structured": 1},
        "source_type_counts": {"synthetic": 1},
    }

    result = validate_eval_dataset(rows=rows, manifest=manifest)

    assert result["ok"] is False
    assert result["errors"] == [
        "row[1].query missing",
        "row[1].query_type invalid",
        "row[1].source_type invalid",
        "row[1].annotation_status invalid",
        "row[1].review_status invalid",
        "row[2].sample_id duplicated",
        "manifest.schema_version invalid",
        "manifest.sample_count mismatch",
        "manifest.query_type_counts mismatch",
        "manifest.source_type_counts mismatch",
    ]
    assert [row["sample_id"] for row in result["rows"]] == ["dup", "dup"]
