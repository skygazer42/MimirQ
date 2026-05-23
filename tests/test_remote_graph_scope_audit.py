from __future__ import annotations

from scripts.remote_graph_scope_audit import (
    build_repeated_query,
    compare_scope_counts,
    summarize_graph_response,
)


def test_remote_graph_scope_audit_build_repeated_query_preserves_repeated_document_ids() -> None:
    query = build_repeated_query("document_ids", ["doc-a", "doc-b"])

    assert query == "document_ids=doc-a&document_ids=doc-b"


def test_remote_graph_scope_audit_summarizes_graph_response_counts() -> None:
    summary = summarize_graph_response(
        {
            "nodes": [{"id": "event-1"}, {"id": "entity-1"}],
            "links": [{"source": "event-1", "target": "entity-1"}],
            "stats": {"events": 1, "entities": 1, "links": 1},
        }
    )

    assert summary == {
        "node_count": 2,
        "link_count": 1,
        "stats": {"events": 1, "entities": 1, "links": 1},
    }


def test_remote_graph_scope_audit_compares_dataset_and_document_scope_counts() -> None:
    comparison = compare_scope_counts(
        dataset_stats={"events": 2, "entities": 5, "links": 5},
        document_stats={"events": 2, "entities": 5, "links": 5},
        dataset_graph={"node_count": 7, "link_count": 9, "stats": {"links": 9}},
        document_graph={"node_count": 7, "link_count": 9, "stats": {"links": 9}},
    )

    assert comparison["stats_match"] is True
    assert comparison["graph_match"] is True
    assert comparison["dataset_stats"] == {"events": 2, "entities": 5, "links": 5}
