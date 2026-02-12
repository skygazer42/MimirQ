from __future__ import annotations


def test_summarize_near_dup_payload_extracts_core_stats() -> None:
    from app.services.dataset_precheck_near_dup_summary import summarize_near_dup_payload

    payload = {
        "threshold": 5,
        "pairs_returned": 10,
        "clusters_returned": 2,
        "clusters": [
            {"id": "c1", "members": ["a", "b", "c"], "keep_candidate": "a"},
            {"id": "c2", "members": ["d", "e"], "keep_candidate": "d"},
        ],
    }

    summary = summarize_near_dup_payload(payload)
    assert summary["enabled"] is True
    assert summary["clusters"] == 2
    assert summary["affected_files"] == 5
    assert summary["largest_cluster_size"] == 3
    assert summary["pairs"] == 10
    assert summary["keep_candidates_sample"] == ["a", "d"]


def test_summarize_near_dup_payload_handles_missing_or_empty() -> None:
    from app.services.dataset_precheck_near_dup_summary import summarize_near_dup_payload

    assert summarize_near_dup_payload(None)["enabled"] is False
    assert summarize_near_dup_payload({})["enabled"] is False

