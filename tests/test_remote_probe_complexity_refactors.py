from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import remote_governance_ingest_matrix as governance_probe
from scripts import remote_graph_scope_audit as graph_probe
from scripts import remote_keyword_bm25_fallback_probe as keyword_probe
from scripts import remote_observability_metrics_probe as observability_probe
from scripts import remote_precheck_batch_probe as precheck_probe
from scripts import remote_table_store_probe as table_probe


@pytest.mark.parametrize(
    ("parser", "expected_base_url", "timeout_field", "expected_timeout"),
    [
        (keyword_probe.parse_args, "http://127.0.0.1:8000", "timeout", 180),
        (governance_probe.parse_args, "http://127.0.0.1:8000", "timeout", 600),
        (graph_probe.parse_args, "http://127.0.0.1:8000", "timeout", 1800),
        (observability_probe.parse_args, "http://127.0.0.1:8000/api/v1", "timeout_sec", 60.0),
        (precheck_probe.parse_args, "http://127.0.0.1:8000", "timeout", 180),
        (table_probe.parse_args, "http://127.0.0.1:8000", "timeout", 180),
    ],
)
def test_cli_defaults_are_preserved(
    parser: object,
    expected_base_url: str,
    timeout_field: str,
    expected_timeout: int | float,
) -> None:
    args = parser([])
    assert args.base_url == expected_base_url
    assert getattr(args, timeout_field) == expected_timeout


@pytest.mark.parametrize(
    ("parser", "flag", "bad_value"),
    [
        (keyword_probe.parse_args, "--timeout", "nope"),
        (governance_probe.parse_args, "--poll-timeout", "bad"),
        (graph_probe.parse_args, "--timeout", "bad"),
        (observability_probe.parse_args, "--timeout-sec", "bad"),
        (precheck_probe.parse_args, "--timeout", "bad"),
        (table_probe.parse_args, "--poll-timeout", "bad"),
    ],
)
def test_cli_invalid_numeric_values_exit(parser: object, flag: str, bad_value: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        parser([flag, bad_value])
    assert exc_info.value.code == 2


def test_keyword_scenarios_are_deterministic() -> None:
    fixtures = {name: Path(f"/tmp/{name}") for name in ("xlsx", "docx", "csv", "yaml", "html")}
    assert [row["name"] for row in keyword_probe.build_keyword_scenarios(fixtures)] == [
        "xlsx_only_bm25",
        "xlsx_mixed_bm25",
    ]


def test_keyword_metrics_and_failure_strings_are_preserved() -> None:
    retrieve_body = {
        "citations": [{"document_id": "doc-other"}],
        "metrics": {
            "retrieval_per_query": [
                {
                    "retriever_debug": {
                        "channels": {
                            "vector": {"candidates": 2},
                            "lexical_db": {"candidates": 3},
                            "keyword_strategy": {"bm25_used": False, "lexical_db_used": True},
                        },
                        "counts": {"bm25_candidates": 0},
                    }
                }
            ]
        },
    }
    chat_body = {
        "citations": [{"document_id": "doc-other"}],
        "response": "EMEA only",
    }

    assert keyword_probe.keyword_metrics(retrieve_body) == {
        "channels": {
            "vector": {"candidates": 2},
            "lexical_db": {"candidates": 3},
            "keyword_strategy": {"bm25_used": False, "lexical_db_used": True},
        },
        "counts": {"bm25_candidates": 0},
    }
    assert keyword_probe.evaluate_keyword_case(
        name="xlsx_only_bm25",
        xlsx_document_id="doc-xlsx",
        retrieve_body=retrieve_body,
        chat_body=chat_body,
        require_first_doc=True,
    ) == [
        "xlsx_only_bm25: retrieve_missing_xlsx actual=['doc-other']",
        "xlsx_only_bm25: chat_missing_xlsx actual=['doc-other']",
        "xlsx_only_bm25: retrieve_first_doc expected=doc-xlsx actual=doc-other",
        "xlsx_only_bm25: chat_first_doc expected=doc-xlsx actual=doc-other",
        "xlsx_only_bm25: vector_candidates expected=0 actual=2",
        "xlsx_only_bm25: bm25_candidates expected>=1 actual=0",
        "xlsx_only_bm25: bm25_used expected=true actual=False",
        "xlsx_only_bm25: lexical_db_used expected=false actual=True",
        "xlsx_only_bm25: lexical_candidates expected=0 actual=3",
        "xlsx_only_bm25: chat_missing_review",
        "xlsx_only_bm25: chat_missing_apac",
    ]


def test_governance_case_failure_strings_are_preserved() -> None:
    case = {
        "expected_status": "completed",
        "required_metadata_keys": ["governance_pii_hits"],
        "required_rule_packs": ["web_navigation"],
        "allowed_drop_reasons": ["outline_only"],
        "present_in_parsed": ["[PII]"],
        "absent_in_chunks": ["secret"],
        "require_citations": True,
    }

    assert governance_probe.evaluate_case_expectations(
        case,
        document_status="failed",
        metadata={},
        parsed_text="plain text",
        chunk_text="secret",
        citation_text="",
        citation_count=0,
    ) == [
        "status expected completed got failed",
        "metadata missing governance_enabled=true",
        "metadata missing non-empty governance_pii_hits",
        "metadata missing rule_pack web_navigation",
        "drop_reasons missing one of ['outline_only']",
        "parsed missing expected text: [PII]",
        "chunks still contains forbidden text: secret",
        "retrieval returned no citations",
    ]


def test_precheck_summary_failure_strings_are_preserved() -> None:
    assert precheck_probe.evaluate_precheck_summary({}, {}) == [
        "total_files expected>=1 actual=0",
        "by_file_type.md expected>=1 actual=None",
        "short_text finding expected>=1 actual=None",
        "representative sample expected non-empty",
    ]


def test_table_store_failure_strings_are_preserved() -> None:
    assert table_probe.validate_table_store_probe(
        table_list_body={"items": [{"row_count": 0, "col_count": 0}]},
        table_detail_body={"columns": [{"name": "region"}], "sample_rows": []},
        table_preview_body={},
        table_query_body={},
    ) == [
        "table_list.row_count expected>=1 actual=0",
        "table_list.col_count expected>=1 actual=0",
        "table_detail.columns expected>=3 actual=[{'name': 'region'}]",
        "table_detail.sample_rows expected non-empty actual=[]",
        "preview.columns expected=['region','amount','status'] actual=None",
        "preview.rows expected>=2 actual=None",
        "query.columns expected=['region','amount','status'] actual=None",
        "query.rows expected>=2 actual=None",
    ]


def test_graph_query_order_and_summary_schema_are_preserved() -> None:
    queries = graph_probe._graph_queries("dataset-1", ["doc-1", "", "doc-2"])
    assert queries["document_stats"] == "/api/v1/kg/stats?document_ids=doc-1&document_ids=doc-2"

    summary = graph_probe.build_graph_audit_summary(
        {
            "dataset_stats": {"entity_count": 2},
            "document_stats": {"entity_count": 2},
            "dataset_graph": {"nodes": [1], "links": [1], "stats": {"edge_count": 1}},
            "document_graph": {"nodes": [1], "links": [1], "stats": {"edge_count": 1}},
            "unscoped_stats": {"entity_count": 9},
            "list_documents": {"items": [{"id": "doc-1"}, {"document_id": "doc-2"}]},
        }
    )
    assert summary == {
        "dataset_stats": {"entity_count": 2},
        "document_stats": {"entity_count": 2},
        "unscoped_stats": {"entity_count": 9},
        "dataset_graph": {"node_count": 1, "link_count": 1, "stats": {"edge_count": 1}},
        "document_graph": {"node_count": 1, "link_count": 1, "stats": {"edge_count": 1}},
        "comparison": {
            "dataset_stats": {"entity_count": 2},
            "document_stats": {"entity_count": 2},
            "dataset_graph": {"node_count": 1, "link_count": 1, "stats": {"edge_count": 1}},
            "document_graph": {"node_count": 1, "link_count": 1, "stats": {"edge_count": 1}},
            "stats_match": True,
            "graph_match": True,
        },
        "list_documents_count": 2,
        "list_document_ids": ["doc-1", "doc-2"],
    }


def test_observability_report_schema_and_metrics_progress_are_preserved() -> None:
    before_summary = {"enabled": True, "rag_trace_count": 3}
    before_query_analytics = {"enabled": True, "rag_trace_count": 3, "zero_hit_count": 1}
    after_summary = {"enabled": True, "rag_trace_count": 4}
    after_query_analytics = {
        "enabled": True,
        "rag_trace_count": 4,
        "unique_query_hashes": 2,
        "zero_hit_count": 2,
        "top_zero_hit_queries": [{"hash": "abc"}],
    }
    assert observability_probe.metrics_progress_satisfied(
        before_summary=before_summary,
        before_query_analytics=before_query_analytics,
        summary_after=after_summary,
        query_analytics_after=after_query_analytics,
        min_trace_delta=1,
        min_zero_hit_delta=1,
    )

    report = observability_probe.build_probe_report(
        args=SimpleNamespace(base_url="http://127.0.0.1:8000/api/v1"),
        started_at=123,
        dataset_id="dataset-1",
        conversation_ids=["conv-1"],
        before_summary=before_summary,
        before_query_analytics=before_query_analytics,
        after_summary=after_summary,
        after_query_analytics=after_query_analytics,
        failures=[],
    )
    assert report == {
        "schema": "mimirq.observability_metrics_probe.v1",
        "started_at_ms": 123,
        "base_url": "http://127.0.0.1:8000/api/v1",
        "dataset_id": "dataset-1",
        "conversation_ids": ["conv-1"],
        "before_summary": {"enabled": True, "rag_trace_count": 3},
        "before_query_analytics": {"enabled": True, "rag_trace_count": 3, "zero_hit_count": 1},
        "after_summary": {"enabled": True, "rag_trace_count": 4},
        "after_query_analytics": {
            "enabled": True,
            "rag_trace_count": 4,
            "unique_query_hashes": 2,
            "zero_hit_count": 2,
            "top_zero_hit_queries": [{"hash": "abc"}],
        },
        "failures": [],
    }


def test_observability_cleanup_order_survives_partial_failures() -> None:
    calls: list[tuple[str, str]] = []

    class FakeApi:
        def delete(self, path: str) -> int:
            calls.append(("delete", path))
            if path.endswith("/conv-1"):
                raise RuntimeError("first delete fails")
            return 204

        def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            calls.append(("post_json", path))
            if "purge" in path:
                raise RuntimeError("purge fails")
            return {}

        def put_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
            calls.append(("put_json", path))
            return {}

    observability_probe.cleanup_probe_resources(
        FakeApi(),
        conversation_ids=["conv-1", "conv-2"],
        dataset_id="dataset-1",
        original_obs={"metrics_log_enabled": False, "metrics_log_include_text": True},
    )
    assert calls == [
        ("delete", "/chat/conversations/conv-1"),
        ("delete", "/chat/conversations/conv-2"),
        ("post_json", "/datasets/dataset-1/purge?dry_run=false&max_delete=1000"),
        ("delete", "/datasets/dataset-1"),
        ("put_json", "/settings"),
    ]


def test_keyword_probe_cleans_up_after_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    order: list[str] = []
    dataset_ids = iter(["dataset-1", "dataset-2"])
    scenario_results = iter(
        [
            {
                "name": "xlsx_only_bm25",
                "dataset_id": "dataset-1",
                "xlsx_document_id": "doc-1",
                "uploaded": [],
                "retrieve_citation_document_ids": ["doc-1"],
                "chat_citation_document_ids": ["doc-1"],
                "ok": True,
                "failures": [],
            },
            {
                "name": "xlsx_mixed_bm25",
                "dataset_id": "dataset-2",
                "xlsx_document_id": "doc-2",
                "uploaded": [],
                "retrieve_citation_document_ids": ["doc-2"],
                "chat_citation_document_ids": ["doc-2"],
                "ok": False,
                "failures": ["xlsx_mixed_bm25: forced_failure"],
            },
        ]
    )

    class FakeApi:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def json(self, method: str, path: str, **_kwargs: object) -> SimpleNamespace:
            assert (method, path) == ("GET", "/api/v1/health")
            return SimpleNamespace(status=200, body={"ok": True}, elapsed_sec=0.0)

    monkeypatch.setattr(keyword_probe, "LiveApi", FakeApi)
    monkeypatch.setattr(
        keyword_probe,
        "prepare_fixture_files",
        lambda _path: {name: Path(f"/tmp/{name}") for name in ("xlsx", "docx", "csv", "yaml", "html")},
    )

    def _create_dataset(_api: object, *, run_id: str, scenario_name: str, steps: list[dict[str, object]]) -> str:
        del run_id, steps
        order.append(f"create:{scenario_name}")
        return next(dataset_ids)

    def _run_scenario(
        _api: object,
        *,
        dataset_id: str,
        scenario: dict[str, object],
        steps: list[dict[str, object]],
        rag_config: dict[str, object],
        poll_timeout: int,
    ) -> dict[str, object]:
        del dataset_id, steps, rag_config, poll_timeout
        order.append(f"run:{scenario['name']}")
        return next(scenario_results)

    def _cleanup_dataset(_api: object, *, steps: list[dict[str, object]], dataset_id: str) -> dict[str, object]:
        del steps
        order.append(f"cleanup:{dataset_id}")
        return {"dataset_id": dataset_id, "delete_dataset_status": 204}

    monkeypatch.setattr(keyword_probe, "create_keyword_dataset", _create_dataset)
    monkeypatch.setattr(keyword_probe, "run_keyword_scenario", _run_scenario)
    monkeypatch.setattr(keyword_probe, "cleanup_dataset", _cleanup_dataset)

    artifact_dir, summary, steps, return_code = keyword_probe.run_keyword_probe(
        SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            tenant_id="tenant",
            account_id="account",
            user_id="user",
            artifact_dir=str(tmp_path / "artifacts"),
            timeout=180,
            poll_timeout=600,
        )
    )

    assert artifact_dir == (tmp_path / "artifacts").resolve()
    assert return_code == 1
    assert summary["ok"] is False
    assert summary["error"] == "keyword fallback case failed xlsx_mixed_bm25: ['xlsx_mixed_bm25: forced_failure']"
    assert [case["name"] for case in summary["cases"]] == ["xlsx_only_bm25", "xlsx_mixed_bm25"]
    assert summary["cleanup"] == [
        {"dataset_id": "dataset-1", "delete_dataset_status": 204},
        {"dataset_id": "dataset-2", "delete_dataset_status": 204},
    ]
    assert steps[0]["name"] == "health"
    assert order == [
        "create:xlsx_only_bm25",
        "run:xlsx_only_bm25",
        "create:xlsx_mixed_bm25",
        "run:xlsx_mixed_bm25",
        "cleanup:dataset-1",
        "cleanup:dataset-2",
    ]
