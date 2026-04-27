from __future__ import annotations


def test_build_cross_dataset_dedup_report_aggregates_enabled_dataset_summaries() -> None:
    from app.services.cross_dataset_dedup_report import build_cross_dataset_dedup_report

    out = build_cross_dataset_dedup_report(
        [
            {
                "dataset_id": "ds-a",
                "dataset_name": "Dataset A",
                "near_dup_summary": {
                    "enabled": True,
                    "pairs": 12,
                    "clusters": 3,
                    "affected_files": 8,
                    "largest_cluster_size": 4,
                    "keep_candidates_sample": ["a1", "a2"],
                },
            },
            {
                "dataset_id": "ds-b",
                "dataset_name": "Dataset B",
                "near_dup_summary": {
                    "enabled": True,
                    "pairs": 5,
                    "clusters": 2,
                    "affected_files": 3,
                    "largest_cluster_size": 2,
                    "keep_candidates_sample": ["b1"],
                },
            },
            {
                "dataset_id": "ds-c",
                "dataset_name": "Dataset C",
                "near_dup_summary": {"enabled": False},
            },
        ]
    )

    assert out["schema"] == "mimirq.cross_dataset_dedup_report.v1"
    assert out["summary"]["dataset_count"] == 3
    assert out["summary"]["enabled_dataset_count"] == 2
    assert out["summary"]["pairs"] == 17
    assert out["summary"]["clusters"] == 5
    assert out["summary"]["affected_files"] == 11
    assert out["summary"]["largest_cluster_size"] == 4
    assert out["datasets"][0]["dataset_id"] == "ds-a"


def test_build_cross_dataset_dedup_report_can_summarize_raw_payloads() -> None:
    from app.services.cross_dataset_dedup_report import build_cross_dataset_dedup_report

    out = build_cross_dataset_dedup_report(
        [
            {
                "dataset_id": "ds-a",
                "dataset_name": "Dataset A",
                "near_dup_payload": {
                    "threshold": 5,
                    "pairs_returned": 4,
                    "clusters": [
                        {"members": ["a", "b", "c"], "keep_candidate": "a"},
                    ],
                },
            }
        ]
    )

    assert out["summary"]["enabled_dataset_count"] == 1
    assert out["summary"]["pairs"] == 4
    assert out["datasets"][0]["affected_files"] == 3
    assert out["datasets"][0]["keep_candidates_sample"] == ["a"]
