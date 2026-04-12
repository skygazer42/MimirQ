from __future__ import annotations


def test_release_gate_parsing_proof_warn_mode_emits_notes() -> None:
    import scripts.release_gate as mod

    summary = {
        "hit_at_k_mean": 0.9,
        "mrr_mean": 0.8,
        "failed_case_ids": ["case-a"],
    }
    cfg = {
        "policy": "warn",
        "thresholds": {
            "hit_at_k_mean": {"min": 1.0},
            "mrr_mean": {"min": 1.0},
            "failed_case_count": {"max": 0},
        },
    }

    violations, notes, observed = mod._gate_parsing_proof_summary(  # noqa: SLF001
        summary=summary,
        cfg=cfg,
    )

    assert len(violations) == 3
    assert notes
    assert observed.get("failed_case_count") == 1


def test_release_gate_parsing_proof_diff_warn_mode_emits_notes() -> None:
    import scripts.release_gate as mod

    diff = {
        "metric_deltas": {"hit_at_k_mean_delta": -0.1, "mrr_mean_delta": -0.2},
        "failed_case_drift": {"added_ids": ["case-a"]},
    }
    cfg = {
        "policy": "warn",
        "thresholds": {
            "hit_at_k_mean_delta": {"min": 0.0},
            "mrr_mean_delta": {"min": 0.0},
            "failed_case_added_count": {"max": 0},
        },
    }

    violations, notes, observed = mod._gate_parsing_proof_diff(  # noqa: SLF001
        diff=diff,
        cfg=cfg,
    )

    assert len(violations) == 3
    assert notes
    assert observed.get("failed_case_added_count") == 1


def test_release_gate_extracts_parsing_proof_markdown_details() -> None:
    import scripts.release_gate as mod

    summary_details = mod._extract_parsing_proof_summary_details(  # noqa: SLF001
        {
            "failed_case_ids": ["case-a", "", None, "case-b"],
        }
    )
    diff_details = mod._extract_parsing_proof_diff_details(  # noqa: SLF001
        {
            "failed_case_drift": {
                "added_ids": ["case-c"],
                "removed_ids": ["case-a", ""],
            }
        }
    )

    assert summary_details == {"failed_case_ids": ["case-a", "case-b"]}
    assert diff_details == {
        "failed_case_added_ids": ["case-c"],
        "failed_case_removed_ids": ["case-a"],
    }
