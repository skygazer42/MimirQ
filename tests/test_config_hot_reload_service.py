from __future__ import annotations


def test_build_config_hot_reload_state_exposes_stable_fingerprints(monkeypatch) -> None:  # noqa: ANN001
    from app.services.config_hot_reload import build_config_hot_reload_state
    from app.services.ops_config_snapshot_service import OpsConfigSnapshot

    snap = OpsConfigSnapshot(
        schema="mimirq.ops_config_snapshot.v1",
        fingerprint="ops-abc123",
        config={"retrieval_fingerprint": "retrieval-xyz789"},
    )
    monkeypatch.setattr(
        "app.services.config_hot_reload.build_ops_config_snapshot",
        lambda: snap,
    )

    state = build_config_hot_reload_state()

    assert state.schema == "mimirq.config_hot_reload.v1"
    assert state.ops_fingerprint == "ops-abc123"
    assert state.retrieval_fingerprint == "retrieval-xyz789"
    assert state.combined_fingerprint


def test_should_hot_reload_config_detects_fingerprint_changes(monkeypatch) -> None:  # noqa: ANN001
    from app.services.config_hot_reload import build_config_hot_reload_state, should_hot_reload_config
    from app.services.ops_config_snapshot_service import OpsConfigSnapshot

    snaps = iter(
        [
            OpsConfigSnapshot(
                schema="mimirq.ops_config_snapshot.v1",
                fingerprint="ops-a",
                config={"retrieval_fingerprint": "retrieval-a"},
            ),
            OpsConfigSnapshot(
                schema="mimirq.ops_config_snapshot.v1",
                fingerprint="ops-b",
                config={"retrieval_fingerprint": "retrieval-b"},
            ),
        ]
    )
    monkeypatch.setattr(
        "app.services.config_hot_reload.build_ops_config_snapshot",
        lambda: next(snaps),
    )

    prev = build_config_hot_reload_state()
    current = build_config_hot_reload_state()

    assert should_hot_reload_config(previous_combined_fingerprint=prev.combined_fingerprint, current_state=current) is True
    assert should_hot_reload_config(previous_combined_fingerprint=current.combined_fingerprint, current_state=current) is False
