from __future__ import annotations

from app.rag.policy.out_of_scope_live_gate import maybe_apply_out_of_scope_live_guard


def test_out_of_scope_live_guard_is_noop_when_disabled() -> None:
    result = maybe_apply_out_of_scope_live_guard(
        query="新型号 X200 怎么接线",
        enabled=False,
        candidate=True,
        current_triggered=True,
        current_reason="citations_lt_min",
        tenant_id="00000000-0000-0000-0000-000000000001",
        dataset_id="00000000-0000-0000-0000-000000000002",
        verifier=lambda: {"verdict": "out_of_scope"},
    )

    assert result["applied"] is False
    assert result["abstain_triggered"] is True
    assert result["abstain_reason"] == "citations_lt_min"


def test_out_of_scope_live_guard_upgrades_reason_when_verdict_is_out_of_scope() -> None:
    result = maybe_apply_out_of_scope_live_guard(
        query="新型号 X200 怎么接线",
        enabled=True,
        candidate=True,
        current_triggered=True,
        current_reason="citations_lt_min",
        tenant_id="00000000-0000-0000-0000-000000000001",
        dataset_id="00000000-0000-0000-0000-000000000002",
        verifier=lambda: {
            "schema": "mimirq.out_of_scope_live_guard.v1",
            "verdict": "out_of_scope",
            "l1_keyword_hit": False,
            "l2_top1_sim": 0.11,
            "l3_hyde_hit": False,
        },
    )

    assert result["applied"] is True
    assert result["abstain_triggered"] is True
    assert result["abstain_reason"] == "out_of_scope"
    assert result["verdict"]["verdict"] == "out_of_scope"
