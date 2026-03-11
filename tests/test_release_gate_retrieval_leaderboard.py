from __future__ import annotations


def test_release_gate_leaderboard_warn_mode_does_not_hard_fail() -> None:
    import scripts.release_gate as mod

    leaderboard = {"rows": [{"label": "base", "retrieval_mrr": 0.50, "retrieval_hit_at_20": 0.80}]}
    cfg = {
        "policy": "warn",
        "thresholds": {"retrieval_mrr": {"min": 0.6}, "retrieval_hit_at_20": {"min": 0.9}},
    }

    violations, notes, observed = mod._gate_retrieval_leaderboard(  # noqa: SLF001
        leaderboard=leaderboard,
        cfg=cfg,
    )

    assert len(violations) == 2
    assert notes
    assert observed.get("label") == "base"


def test_release_gate_leaderboard_fail_mode_exposes_violation_details() -> None:
    import scripts.release_gate as mod

    leaderboard = {"rows": [{"label": "best", "retrieval_mrr": 0.55}]}
    cfg = {"policy": "fail", "thresholds": {"retrieval_mrr": {"min": 0.7}}}

    violations, notes, observed = mod._gate_retrieval_leaderboard(  # noqa: SLF001
        leaderboard=leaderboard,
        cfg=cfg,
    )

    assert len(violations) == 1
    v = violations[0]
    assert v.area == "retrieval_leaderboard"
    assert v.metric == "retrieval_mrr"
    assert "min" in (v.threshold or {})
    assert not notes
    assert observed.get("label") == "best"
