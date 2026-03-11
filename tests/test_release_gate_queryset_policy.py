from __future__ import annotations


def test_release_gate_queryset_policy_warn_mode_emits_note() -> None:
    import scripts.release_gate as mod

    snapshot = {
        "policy_source": "policy_json+cli_overrides",
        "policy_hash": "abc123abc123abc123abc123",
        "trend": {"policy_changed": True},
    }
    cfg = {"policy": "warn"}

    violations, notes, observed = mod._gate_queryset_policy_snapshot(  # noqa: SLF001
        snapshot=snapshot,
        cfg=cfg,
    )

    assert not violations
    assert notes
    assert observed.get("policy_changed") is True
    assert observed.get("policy_hash") == "abc123abc123abc123abc123"


def test_release_gate_queryset_policy_fail_mode_raises_violation() -> None:
    import scripts.release_gate as mod

    snapshot = {
        "policy_source": "policy_json",
        "policy_hash": "def456def456def456def456",
        "trend": {"policy_changed": True},
    }
    cfg = {"policy": "fail"}

    violations, notes, observed = mod._gate_queryset_policy_snapshot(  # noqa: SLF001
        snapshot=snapshot,
        cfg=cfg,
    )

    assert len(violations) == 1
    v = violations[0]
    assert v.area == "queryset_health"
    assert v.metric == "policy_changed"
    assert not notes
    assert observed.get("policy_changed") is True
