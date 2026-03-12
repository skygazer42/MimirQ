from __future__ import annotations


def test_resolve_retrieval_contract_policy_deterministic_recall_defaults() -> None:
    from app.rag.retrieval.contract import resolve_retrieval_contract_policy

    policy = resolve_retrieval_contract_policy(
        mode="deterministic_recall",
        requested_top_k=5,
        hard_fallback_enabled_setting=False,
        hard_fallback_mode_setting="hybrid",
        hard_fallback_top_k_setting=8,
        visible_evidence_only_setting=False,
        evidence_span_strict_setting=False,
    )

    assert policy["mode"] == "deterministic_recall"
    assert policy["deterministic_recall"] is True
    assert policy["hard_fallback_enabled"] is True
    assert policy["hard_fallback_mode"] == "keyword"
    assert int(policy["hard_fallback_top_k"] or 0) >= 20
    assert int(policy["hard_fallback_top_k"] or 0) >= 5
    assert policy["require_evidence_spans"] is False
    assert policy["force_visible_evidence_only"] is False


def test_resolve_retrieval_contract_policy_evidence_strict_enforces_spans_and_visible() -> None:
    from app.rag.retrieval.contract import resolve_retrieval_contract_policy

    policy = resolve_retrieval_contract_policy(
        mode="evidence_strict",
        requested_top_k=10,
        hard_fallback_enabled_setting=False,
        hard_fallback_mode_setting="keyword",
        hard_fallback_top_k_setting=30,
        visible_evidence_only_setting=False,
        evidence_span_strict_setting=False,
    )

    assert policy["mode"] == "evidence_strict"
    assert policy["deterministic_recall"] is False
    assert policy["require_evidence_spans"] is True
    assert policy["force_visible_evidence_only"] is True
    assert policy["claim_check_required"] is True
    assert policy["hard_fallback_enabled"] is False

