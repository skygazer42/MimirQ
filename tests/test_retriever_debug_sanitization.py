from __future__ import annotations


def test_sanitize_retriever_debug_does_not_include_query_text() -> None:
    from app.rag.retrieval.orchestrator import _sanitize_retriever_debug

    dbg = {
        "requested_k": 5,
        "search_k": 10,
        "query_normalization": {
            "original": "user secret query",
            "normalized": "user secret query",
            "applied_rules": ["strip", "lower"],
        },
    }

    out = _sanitize_retriever_debug(dbg)
    assert isinstance(out, dict)

    qn = out.get("query_normalization") or {}
    assert isinstance(qn, dict)
    assert "original" not in qn
    assert "normalized" not in qn
    assert qn.get("original_chars") == len("user secret query")
    assert qn.get("normalized_chars") == len("user secret query")
    assert qn.get("applied_rules") == ["strip", "lower"]


def test_sanitize_retriever_debug_includes_enrich_filter_counters() -> None:
    from app.rag.retrieval.orchestrator import _sanitize_retriever_debug

    dbg = {
        "enrich_pass1": {
            "input_results": 10,
            "filtered_acl": 2,
            "filtered_dataset": 1,
            "filtered_not_ready": 1,
            "filtered_embedding_space": 1,
            "filtered_pipeline_version": 0,
            "filtered_metadata_filter": 3,
            "output_results": 2,
            "exception": "DB error: should not leak",
        },
        "enrich_pass2": {
            "input_results": 4,
            "filtered_acl": 0,
            "filtered_dataset": 0,
            "filtered_not_ready": 0,
            "filtered_embedding_space": 0,
            "filtered_pipeline_version": 1,
            "filtered_metadata_filter": 1,
            "output_results": 2,
        },
    }

    out = _sanitize_retriever_debug(dbg)
    assert isinstance(out, dict)

    ep1 = out.get("enrich_pass1") or {}
    assert isinstance(ep1, dict)
    assert ep1 == {
        "input_results": 10,
        "output_results": 2,
        "filtered_acl": 2,
        "filtered_dataset": 1,
        "filtered_not_ready": 1,
        "filtered_embedding_space": 1,
        "filtered_pipeline_version": 0,
        "filtered_metadata_filter": 3,
        "filtered_orphaned": 0,
    }

    ep2 = out.get("enrich_pass2") or {}
    assert isinstance(ep2, dict)
    assert ep2["input_results"] == 4
    assert ep2["filtered_pipeline_version"] == 1
    assert ep2["filtered_metadata_filter"] == 1
    assert "exception" not in ep2


def test_sanitize_retriever_debug_includes_governance_policy_summary() -> None:
    from app.rag.retrieval.orchestrator import _sanitize_retriever_debug

    dbg = {
        "governance_policy": {
            "enabled": True,
            "prefer_authority": True,
            "prefer_latest": False,
            "filter_superseded": True,
            "input_results": 10,
            "output_results": 7,
            "candidate_docs": 4,
            "filtered_superseded": 2,
            "reordered": True,
            "avg_boost": 0.001,
            "max_boost": 0.02,
            # Should not be leaked by sanitizer (scope identifiers).
            "dataset_id": "ds-secret",
        }
    }

    out = _sanitize_retriever_debug(dbg)
    assert isinstance(out, dict)
    gp = out.get("governance_policy") or {}
    assert isinstance(gp, dict)
    assert gp.get("enabled") is True
    assert gp.get("prefer_authority") is True
    assert gp.get("filter_superseded") is True
    assert gp.get("filtered_superseded") == 2
    assert "dataset_id" not in gp
