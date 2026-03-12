from __future__ import annotations


def test_release_gate_queryset_diff_warn_mode_emits_notes() -> None:
    import scripts.release_gate as mod

    diff = {
        "hard_case_drift": {"added_ids": ["q-1"]},
        "degradation_flags_drift": {"added_flags": ["mrr_drop"]},
        "parse_risk_tail_drift": {"added_document_ids": ["doc-1"]},
    }
    cfg = {
        "policy": "warn",
        "thresholds": {
            "hard_case_added_count": {"max": 0},
            "degradation_flag_added_count": {"max": 0},
            "parse_risk_tail_added_count": {"max": 0},
        },
    }

    violations, notes, observed = mod._gate_queryset_health_diff(  # noqa: SLF001
        diff=diff,
        cfg=cfg,
    )

    assert len(violations) == 3
    assert notes
    assert observed.get("hard_case_added_count") == 1
    assert observed.get("degradation_flag_added_count") == 1
    assert observed.get("parse_risk_tail_added_count") == 1


def test_release_gate_queryset_diff_fail_mode_exposes_violation_details() -> None:
    import scripts.release_gate as mod

    diff = {
        "hard_case_drift": {"added_ids": ["q-1", "q-2"]},
        "degradation_flags_drift": {"added_flags": []},
        "parse_risk_tail_drift": {"added_document_ids": []},
    }
    cfg = {
        "policy": "fail",
        "thresholds": {
            "hard_case_added_count": {"max": 1},
        },
    }

    violations, notes, observed = mod._gate_queryset_health_diff(  # noqa: SLF001
        diff=diff,
        cfg=cfg,
    )

    assert len(violations) == 1
    v = violations[0]
    assert v.area == "queryset_health_diff"
    assert v.metric == "hard_case_added_count"
    assert not notes
    assert observed.get("hard_case_added_count") == 2
