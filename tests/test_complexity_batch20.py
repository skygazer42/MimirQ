from __future__ import annotations

import datetime as dt
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _ensure_datetime_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dt, "UTC", timezone.utc, raising=False)


def test_read_jsonl_tail_drops_partial_first_line_and_skips_bad_rows(tmp_path: Path) -> None:
    from app.services.hardcase_discovery_service import read_jsonl_tail

    long_prefix = '{"id":0,"pad":"' + ("x" * 240) + '"}\n'
    payload = long_prefix + '{"id":1}\n' + "not-json\n" + '["ignored"]\n' + '{"id":2}\n'
    path = tmp_path / "events.jsonl"
    path.write_text(payload, encoding="utf-8")

    records, truncated = read_jsonl_tail(path, max_bytes=48)

    assert truncated is True
    assert records == [{"id": 1}, {"id": 2}]


def test_plan_feedback_hardcase_candidates_dedupes_request_error_counts_and_prefers_latest_trace() -> None:
    from app.services.hardcase_discovery_service import plan_feedback_hardcase_candidates

    candidates = plan_feedback_hardcase_candidates(
        feedback_rows=[
            {"feedback_id": "fb-1", "request_id": "req-1"},
            {"feedback_id": "fb-2", "request_id": "req-1"},
            {"feedback_id": "fb-3", "request_id": "req-2"},
            {"feedback_id": "fb-4", "request_id": "req-3"},
        ],
        trace_index={
            "req-1": {
                "request_id": "req-1",
                "question_hash": "qh-a",
                "ts_ms": 100,
                "retrieval_config_hash": "cfg-a",
                "citations_count": 2,
                "retrieval_error_kinds": {"timeout": 1},
            },
            "req-2": {
                "request_id": "req-2",
                "question_hash": "qh-a",
                "ts_ms": 200,
                "retrieval_config_hash": "cfg-b",
                "citations_count": 4,
                "retrieval_error_kinds": {"timeout": 2, "empty": 1},
                "rag_config_template": {"version": 1, "patch_hash": "patch-1"},
            },
            "req-3": {
                "request_id": "req-3",
                "question_hash": "qh-b",
                "ts_ms": 50,
                "retrieval_config_hash": "cfg-c",
                "citations_count": 1,
                "retrieval_error_kinds": {"other": 3},
            },
        },
        existing_feedback_ids={"fb-existing"},
        existing_question_hashes={"qh-b"},
        max_candidates=10,
        include_existing=False,
    )

    assert candidates == [
        {
            "question_hash": "qh-a",
            "cluster_size": 3,
            "in_suite": False,
            "feedback_ids": ["fb-1", "fb-2", "fb-3"],
            "request_ids": ["req-1", "req-2"],
            "retrieval_config_hash": "cfg-b",
            "citations_count": 4,
            "retrieval_error_kinds": {"empty": 1, "timeout": 3},
            "rag_config_template": {"version": 1, "patch_hash": "patch-1"},
        }
    ]


def test_normalize_reference_sources_dedupes_and_coerces_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_datetime_utc(monkeypatch)
    from app.services.ltr_rollout_workflow import normalize_reference_sources

    document_id = "00000000-0000-0000-0000-000000000001"
    chunk_id = "00000000-0000-0000-0000-000000000002"

    normalized = normalize_reference_sources(
        [
            {
                "document_id": document_id,
                "chunk_id": chunk_id,
                "page_number": "2",
                "start_char": "5",
                "end_char": 9,
                "chunk_index": 0,
                "doc_pipeline_key": "pipe-1",
                "pipeline_hash": "hash-1",
                "quote": "quoted text",
                "label": "alpha",
            },
            {
                "document_id": document_id,
                "chunk_id": chunk_id,
                "page_number": 99,
            },
            {
                "document_id": "invalid",
                "chunk_id": chunk_id,
            },
        ]
    )

    assert normalized == [
        {
            "document_id": document_id,
            "chunk_id": chunk_id,
            "page_number": 2,
            "start_char": 5,
            "end_char": 9,
            "chunk_index": 0,
            "doc_pipeline_key": "pipe-1",
            "pipeline_hash": "hash-1",
            "quote": "quoted text",
            "label": "alpha",
        }
    ]


def test_comparison_metric_value_uses_named_sections_and_nested_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_datetime_utc(monkeypatch)
    from app.services.ltr_rollout_workflow import _comparison_metric_value

    comparison = {
        "deltas": {"retrieval_mrr": 0.125},
        "candidate_metrics": {"hit": 0.8},
        "baseline_eval_summary": {"cases_total": 12},
        "nested": {"path": {"value": "1.5"}},
    }

    assert _comparison_metric_value(comparison=comparison, metric_key="delta.retrieval_mrr") == 0.125
    assert _comparison_metric_value(comparison=comparison, metric_key="candidate.hit") == 0.8
    assert _comparison_metric_value(comparison=comparison, metric_key="baseline.cases_total") == 12.0
    assert _comparison_metric_value(comparison=comparison, metric_key="nested.path.value") == 1.5
    assert _comparison_metric_value(comparison=comparison, metric_key="candidate.unknown") is None


def test_render_regression_run_diff_html_redacts_ids_and_renders_sections() -> None:
    from app.services.regression_run_diff_html import render_regression_run_diff_html

    html = render_regression_run_diff_html(
        title="Regression Diff",
        base_run_id="base-run",
        target_run_id="target-run",
        generated_at=datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc),
        redact=True,
        diff={
            "diff_score": {
                "version": "v1",
                "base_score": 0.5,
                "target_score": 0.7,
                "delta": 0.2,
                "used_metric_keys": ["retrieval_mrr"],
            },
            "metric_diffs": [{"key": "retrieval_mrr", "before": 0.5, "after": 0.7, "delta": 0.2}],
            "slice_diffs": {
                "file_type": {
                    "buckets": [
                        {
                            "key": "pdf",
                            "items_before": 2,
                            "items_after": 3,
                            "metrics": [{"key": "retrieval_mrr", "before": 0.1, "after": 0.2, "delta": 0.1}],
                        }
                    ]
                }
            },
        },
    )

    assert "[REDACTED]" in html
    assert "retrieval_mrr" in html
    assert "Slice · file_type" in html
    assert "0.5000" in html
    assert "Raw JSON" in html


def test_strip_text_fields_for_metrics_hashes_text_and_sanitizes_kg_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_datetime_utc(monkeypatch)
    from app.core.config import settings
    from app.services.metrics_logger import _strip_text_fields_for_metrics

    monkeypatch.setattr(settings, "METRICS_LOG_INCLUDE_TEXT", False, raising=False)

    stripped = _strip_text_fields_for_metrics(
        {
            "event": "rag_trace",
            "question": "How do I reset it?",
            "query_for_retrieval": "reset flow",
            "citations": [
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "content": "should be removed",
                    "kg_path_provenance": {
                        "schema": "mimirq.kg.v1",
                        "kind": "shortest_path",
                        "hops": "2",
                        "nodes": [
                            {
                                "kind": "entity",
                                "entity_id": "entity-1",
                                "chunk_id": "chunk-1",
                                "evidence_text": "drop me",
                            }
                        ],
                        "edges": [
                            {
                                "kind": "relation",
                                "predicate": "uses",
                                "relation_id": "rel-1",
                                "evidence_source": "kg",
                                "raw_text": "drop me too",
                            }
                        ],
                    },
                }
            ],
        }
    )

    assert "question" not in stripped
    assert "query_for_retrieval" not in stripped
    assert stripped["question_chars"] == len("How do I reset it?")
    assert stripped["query_chars"] == len("reset flow")
    assert stripped["citations"] == [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "kg_path_provenance": {
                "schema": "mimirq.kg.v1",
                "kind": "shortest_path",
                "hops": 2,
                "nodes": [{"kind": "entity", "entity_id": "entity-1", "chunk_id": "chunk-1"}],
                "edges": [
                    {
                        "kind": "relation",
                        "predicate": "uses",
                        "relation_id": "rel-1",
                        "evidence_source": "kg",
                    }
                ],
            },
        }
    ]


def test_mineru_pick_extract_item_prefers_data_id_then_filename_then_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_datetime_utc(monkeypatch)
    from app.services.mineru_service import MinerUService

    extract_result = [
        {"data_id": "data-1", "file_name": "a.pdf", "state": "running"},
        {"data_id": "data-2", "file_name": "b.pdf", "state": "done"},
    ]

    assert MinerUService._pick_extract_item(extract_result, data_id="data-2") == extract_result[1]
    assert MinerUService._pick_extract_item(extract_result, filename="a.pdf") == extract_result[0]
    assert MinerUService._pick_extract_item([extract_result[0]]) == extract_result[0]


def test_mineru_extract_markdown_from_zip_bytes_prefers_full_md(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_datetime_utc(monkeypatch)
    from app.services.mineru_service import MinerUService

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nested/output.md", "fallback")
        zf.writestr("full.md", "preferred")

    assert MinerUService._extract_markdown_from_zip_bytes(buf.getvalue()) == "preferred"


def test_indexer_row_named_value_preserves_missing_key_semantics_for_tuple_metadata() -> None:
    from app.services.indexer import _row_named_value

    row = ({"embedding_space_hash": "space-a"},)

    assert _row_named_value(row, "embedding_space_hash") == "space-a"
    assert _row_named_value(row, "vector_collection_name") is None
