import datetime as dt
import sys
import types
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

if not hasattr(dt, "UTC"):
    from datetime import timezone

    dt.UTC = timezone.utc


class _AttrNamespace(SimpleNamespace):
    def __getattr__(self, _name: str) -> Any:
        return None


def test_chunk_quality_gate_and_summary_preserve_threshold_outputs() -> None:
    from app.services.chunk_quality_gate import compute_chunk_quality_gate
    from app.services.chunk_quality_scoring import summarize_retrieved_chunk_quality

    gate, recs, patches = compute_chunk_quality_gate(
        stats={
            "count": 12_001,
            "short_count": 0,
            "duplicate_count": 2,
            "covered_chars": 0,
            "coverage_ratio": 1.0,
            "overlap_waste_ratio": 0.4,
            "gap_count": 0,
        },
        total_chunks=12_001,
        total_characters=0,
        chunk_size=1000,
        chunk_overlap=300,
        original_text_included=False,
        original_text_truncated=True,
        original_text_max_chars=60_000,
    )

    assert gate["grade"] == "warn"
    assert recs == [
        "Consider reducing chunk_overlap (enterprise cost control).",
        "Increase chunk_size or switch strategy; very high chunk counts hurt latency and cost.",
        "Original text omitted due to size; increase original_text_max_chars if you need precise highlighting.",
    ]
    patch_ids = [patch["id"] for patch in patches]
    assert patch_ids == [
        "tune_overlap",
        "increase_chunk_size",
        "increase_original_text_max_chars",
    ]

    docs = [
        SimpleNamespace(
            id="doc-1",
            metadata={
                "chunk_id": "chunk-1",
                "chunk_quality": {
                    "grade": "GOOD",
                    "score": "0.81",
                    "labels": ["Header", "header", "Noise", "Extra"],
                },
            },
        ),
        SimpleNamespace(
            id="doc-2",
            metadata={
                "chunk_id": "chunk-2",
                "chunk_quality_score": "0.33",
            },
        ),
    ]
    summary = summarize_retrieved_chunk_quality(docs, max_candidates=5, max_items=2)

    assert summary == {
        "schema": "mimirq.chunk_quality_trace.v1",
        "candidates_considered": 2,
        "bucket_counts": {"good": 1, "ok": 0, "bad": 0, "unknown": 1},
        "score_summary": {"count": 2, "avg": 0.57, "p50": 0.33, "p90": 0.33},
        "top_candidates": [
            {
                "rank": 1,
                "chunk_id": "doc-1",
                "grade": "good",
                "score": 0.81,
                "labels": ["header", "noise", "extra"],
            },
            {
                "rank": 2,
                "chunk_id": "doc-2",
                "grade": "unknown",
                "score": 0.33,
                "labels": [],
            },
        ],
    }


def test_ingestion_policy_normalizes_rules_and_fails_soft_on_invalid_metadata() -> None:
    from app.api.schemas.ingestion_policy import IngestionPolicy
    from app.services.ingestion_policy import (
        match_ingestion_rule,
        parse_ingestion_policy_from_metadata,
        validate_and_normalize_ingestion_policy,
    )

    policy = IngestionPolicy(
        version="1",
        rules=[
            {
                "id": "rule.pdf",
                "name": " PDF rule ",
                "match": {"extensions": ["PDF", ".pdf", "txt"]},
                "preprocess": {
                    "enabled": False,
                    "steps": [{"id": "text.strip_bom", "params": {}}],
                },
                "parser_backend": " PyMuPDF ",
                "chunk_strategy": " Markdown_Header ",
                "governance_profile_ref": " builtin:strict ",
                "pipeline_patch": {},
            }
        ],
    )

    normalized = validate_and_normalize_ingestion_policy(policy)
    rule = normalized.rules[0]

    assert rule.name == "PDF rule"
    assert rule.match.extensions == [".pdf", ".txt"]
    assert rule.preprocess.enabled is False
    assert rule.preprocess.steps == []
    assert rule.parser_backend == "pymupdf"
    assert rule.chunk_strategy == "markdown_header"
    assert rule.governance_profile_ref == "builtin:strict"
    assert match_ingestion_rule(normalized, filename="Quarterly.PDF", file_ext="PDF").id == "rule.pdf"

    assert (
        parse_ingestion_policy_from_metadata(
            {
                "ingestion_policy": {
                    "version": "1",
                    "rules": [{"id": "bad", "name": "Bad", "match": {"filename_regex": "("}}],
                }
            }
        )
        is None
    )


def test_fusion_weight_services_preserve_observability_and_learning_contracts() -> None:
    from app.services.fusion_weight_learning_service import (
        suggest_tenant_fusion_weights,
        summarize_fusion_weight_observability,
    )

    tenant_id = "tenant-1"
    reference_sources = [{"document_id": "doc-1", "chunk_id": "chunk-1"}]
    citations = [
        {
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "vector_score": 0.9,
            "bm25_score": 0.2,
            "lexical_score": 0.1,
            "sparse_score": 0.0,
        },
        {
            "document_id": "doc-9",
            "chunk_id": "chunk-9",
            "vector_score": 0.1,
            "bm25_score": 0.05,
            "lexical_score": 0.4,
            "sparse_score": 0.2,
        },
    ]
    trace_snapshot = {
        "tenant_id": tenant_id,
        "retrieval": {
            "channels": {
                "fusion_strategy": "rrf",
                "rrf_k": 60,
                "fusion_weights": {"vector": 0.4, "bm25": 0.2, "lexical": 0.2, "sparse": 0.2},
            }
        },
        "citations": citations,
    }
    rows = [
        {"event": "rag_trace", "tenant_id": tenant_id, **trace_snapshot},
        {
            "schema": "mimirq.training_export_row.v1",
            "tenant_id": tenant_id,
            "reference_sources": reference_sources,
            "trace_snapshot": trace_snapshot,
        },
    ]

    observability = summarize_fusion_weight_observability(rows, tenant_id=tenant_id)

    assert observability == {
        "schema": "mimirq.fusion_weight_observability.v1",
        "tenant_id": tenant_id,
        "summary": {
            "observed_rows": 2,
            "ltr_training_ready_rows": 1,
            "fusion_strategy_histogram": {"rrf": 2},
            "rrf_k_histogram": {"60": 2},
            "channel_signal_coverage": {"vector": 4, "bm25": 4, "lexical": 4, "sparse": 2},
            "observed_weight_profiles": {"vector:0.400,bm25:0.200,lexical:0.200,sparse:0.200": 2},
        },
    }

    learned = suggest_tenant_fusion_weights(rows * 5, tenant_id=tenant_id, min_rows=5)

    assert learned["schema"] == "mimirq.tenant_fusion_weights.v1"
    assert learned["tenant_id"] == tenant_id
    assert learned["summary"]["training_rows"] == 5
    assert learned["summary"]["weight_source"] == "feedback_trace_snapshot"
    assert learned["fusion_weights"]["vector"] > learned["fusion_weights"]["bm25"]
    assert learned["fusion_weights"]["bm25"] > learned["fusion_weights"]["sparse"]
    assert pytest.approx(sum(learned["fusion_weights"].values()), abs=1e-6) == 1.0


def test_access_graph_diff_preserves_changed_fields_and_top_churn() -> None:
    from app.services.access_graph_diff_service import diff_access_graph_records

    records_a = [
        {"kind": "group", "id": "group-1", "name": "Admins", "external_id": "ext-1"},
        {"kind": "dataset", "id": "dataset-1", "permission": "read", "owner_id": "owner-1", "name": "Alpha"},
        {"kind": "document", "id": "doc-1", "dataset_id": "dataset-1", "access_mode": "inherit", "owner_id": "owner-1"},
        {"kind": "group_member", "group_id": "group-1", "user_id": "user-1"},
        {"kind": "dataset_member_permission", "dataset_id": "dataset-1", "account_id": "acct-1"},
        {"kind": "ignored"},
    ]
    records_b = [
        {"kind": "group", "id": "group-1", "name": "Admins", "external_id": "ext-2"},
        {"kind": "dataset", "id": "dataset-1", "permission": "write", "owner_id": "owner-1", "name": "Alpha 2"},
        {"kind": "document", "id": "doc-1", "dataset_id": "dataset-2", "access_mode": "explicit", "owner_id": "owner-2"},
        {"kind": "group_member", "group_id": "group-1", "user_id_hash": "user-hash-2"},
        {"kind": "dataset_member_permission", "dataset_id": "dataset-1", "account_id": "acct-1"},
    ]

    diff = diff_access_graph_records(records_a, records_b, max_examples=5)

    assert diff["summary"]["kinds"]["group"]["changed"] == 1
    assert diff["summary"]["kinds"]["dataset"]["changed"] == 1
    assert diff["summary"]["kinds"]["document"]["changed"] == 1
    assert diff["summary"]["kinds"]["group_member"]["added"] == 1
    assert diff["summary"]["kinds"]["group_member"]["removed"] == 1
    assert diff["examples"]["group_changed"] == [{"id": "group-1", "changed_fields": ["external_id_hash"]}]
    assert diff["examples"]["dataset_changed"] == [
        {"id": "dataset-1", "changed_fields": ["permission", "name_hash"]}
    ]
    assert diff["examples"]["document_changed"] == [
        {"id": "doc-1", "changed_fields": ["dataset_id", "access_mode", "owner_id_hash"]}
    ]
    assert diff["summary"]["top_churn"]["group_member_by_group_id"] == [
        {"group_id": "group-1", "added": 1, "removed": 1}
    ]


@pytest.mark.asyncio
async def test_stream_graph_chat_events_preserve_event_order_and_result_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_stream_graph as chat_stream_graph
    import app.services.chat_tag_service as chat_tag_service

    tag_calls: list[dict[str, object]] = []
    rollback_calls: list[str] = []

    def build_chat_tag_context_docs(_db: Any, **kwargs: Any) -> tuple[list[str], dict[str, Any]]:
        tag_calls.append(kwargs)
        return ["doc"], {"enabled": True, "used": True}

    fake_langgraph = types.ModuleType("app.rag.pipelines.langgraph")
    fake_langgraph.build_rag_state = lambda **_kwargs: {"seed": True}
    fake_langgraph.rag_workflow = SimpleNamespace(
        stream=lambda _state, **_kwargs: iter(
            [
                ("custom", {"phase": "retrieve"}),
                ("values", {"citations": [{"id": "c1"}]}),
                ("values", {"answer": "graph-answer", "metrics": {"route": "graph-route"}}),
            ]
        )
    )

    monkeypatch.setattr(chat_tag_service, "build_chat_tag_context_docs", build_chat_tag_context_docs, raising=True)
    monkeypatch.setitem(sys.modules, "app.rag.pipelines.langgraph", fake_langgraph)
    monkeypatch.setattr(chat_stream_graph.settings, "VECTOR_BACKEND", "pgvector", raising=False)

    db = SimpleNamespace(rollback=lambda: rollback_calls.append("rollback"))
    request = SimpleNamespace(message="Where is it?", structured_output=False, structured_preset=None)
    effective_rag_config = _AttrNamespace(retrieval_mode="hybrid", top_k=4, use_graph=True)
    context = chat_stream_graph.ChatExecutionContext(
        db=db,
        tenant_id=uuid.uuid4(),
        account_id="acct-1",
        request=request,
        conversation_id=None,
        request_id="graph-req-1",
        doc_ids_to_use=[],
        history_for_llm=[],
        scope_dataset_id=None,
        dataset_id_used=None,
        effective_rag_config=effective_rag_config,
        effective_prompt_template_id=None,
        effective_prompt_template_key=None,
        effective_prompt_ab_experiment_key=None,
        rag_config_template_meta=None,
    )

    result_holder: dict[str, object] = {}
    events = [event async for event in chat_stream_graph.stream_graph_chat_events(context=context, result_holder=result_holder)]

    assert [event["type"] for event in events] == ["event", "graph", "citations", "token"]
    assert events[0]["data"]["message"] == "尝试表格查询（TAG）…"
    assert events[1]["data"] == {"phase": "retrieve"}
    assert events[2]["data"] == [{"id": "c1"}]
    assert events[3]["data"]["content"] == "graph-answer"
    assert result_holder == {
        "content": "graph-answer",
        "citations": [{"id": "c1"}],
        "metrics": {"route": "graph-route", "model_used": None},
        "structured_data": None,
    }
    assert rollback_calls == ["rollback"]
    assert tag_calls and "must_recall_expected_source_keys" not in tag_calls[0]
