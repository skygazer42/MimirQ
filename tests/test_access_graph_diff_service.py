from __future__ import annotations

from app.services.access_graph_diff_service import diff_access_graph_records


def test_access_graph_diff_counts_changes_are_bounded():  # noqa: ANN001
    records_a = [
        {"kind": "group", "id": "g1", "name": "Admins", "name_hash": "h_admins", "external_id_hash": "h_ext1"},
        {"kind": "group_member", "id": "gm1", "group_id": "g1", "user_id": "alice", "user_id_hash": "u_alice"},
        {"kind": "dataset", "id": "d1", "permission": "only_me", "name": "Secret", "name_hash": "h_secret"},
    ]
    records_b = [
        # group changed (name_hash changed) but id stays the same.
        {"kind": "group", "id": "g1", "name": "Admins2", "name_hash": "h_admins2", "external_id_hash": "h_ext1"},
        # membership churn (remove alice, add bob)
        {"kind": "group_member", "id": "gm2", "group_id": "g1", "user_id": "bob", "user_id_hash": "u_bob"},
        # dataset permission changed
        {"kind": "dataset", "id": "d1", "permission": "all_team_members", "name": "Secret2", "name_hash": "h_secret2"},
    ]

    diff = diff_access_graph_records(records_a, records_b, max_examples=5)
    assert diff["schema"] == "mimirq.access_graph_diff.v1"

    kinds = diff["summary"]["kinds"]
    assert kinds["group"]["changed"] == 1
    assert kinds["group_member"]["added"] == 1
    assert kinds["group_member"]["removed"] == 1
    assert kinds["dataset"]["changed"] == 1

    churn = diff["summary"]["top_churn"]["group_member_by_group_id"]
    assert churn and churn[0]["group_id"] == "g1"
    assert churn[0]["added"] == 1
    assert churn[0]["removed"] == 1

    # Bounded examples.
    assert len(diff["examples"]["group_changed"]) <= 5
    assert len(diff["examples"]["dataset_changed"]) <= 5

