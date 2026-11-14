import pytest

from app.rag.retrieval.orchestration.channel_budget import resolve_channel_budget_policy_overrides
from app.rag.retrieval.orchestration.query_contracts import SparseQuerySettings
from app.rag.retrieval.orchestration.query_routing import resolve_query_routing


@pytest.mark.parametrize("profile,expected", [(None, None), ("", ""), (" FAST ", "fast")])
def test_channel_budget_preserves_profile_absence_while_selecting_mode_policy(
    profile: str | None, expected: str | None
) -> None:
    overrides, metadata = resolve_channel_budget_policy_overrides(
        policy={"profiles": {"vector": {"fusion_budgets": {"vector": 3}}}},
        retrieval_mode="vector",
        retrieval_profile=profile,
    )

    assert overrides["fusion_budgets"] == {"vector": 3}
    assert metadata["used"] is True
    assert metadata["selected_profile"] == "vector"
    assert metadata["retrieval_profile"] == expected


def test_channel_budget_keeps_absent_profile_when_policy_has_no_match() -> None:
    overrides, metadata = resolve_channel_budget_policy_overrides(
        policy={"profiles": {"bm25": {"fusion_budgets": {"bm25": 3}}}},
        retrieval_mode="vector",
        retrieval_profile=None,
    )

    assert overrides == {}
    assert metadata["used"] is False
    assert metadata["reason"] == "profile_not_found"
    assert metadata["retrieval_profile"] is None


def test_query_routing_keeps_absent_profile_consistent_in_budget_diagnostics() -> None:
    decision = resolve_query_routing(
        "policy",
        options={
            "retrieval_mode": "vector",
            "channel_budget_policy": {"profiles": {"vector": {"fusion_budgets": {"vector": 3}}}},
        },
        sparse=SparseQuerySettings(enabled=False, provider="deterministic"),
    )

    assert decision.normalization.profile_norm is None
    assert decision.channel_metadata["retrieval_profile"] is None
    assert decision.channel_metadata["used"] is True
    assert decision.normalization.retriever_update["fusion_budgets"] == {"vector": 3}
