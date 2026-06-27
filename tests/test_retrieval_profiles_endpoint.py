from __future__ import annotations


def test_retrieval_profiles_endpoint_exposes_supported_profiles_and_version_hash() -> None:
    import app.api.v1.retrieval_profiles as api_mod

    payload = api_mod.get_retrieval_profiles()

    assert payload.get("schema") == "mimirq.retrieval_profiles.v1"
    assert isinstance(payload.get("version_hash"), str)
    assert len(str(payload.get("version_hash") or "")) >= 16

    profiles = payload.get("profiles")
    assert isinstance(profiles, list) and profiles

    names = {str((row or {}).get("name") or "") for row in profiles if isinstance(row, dict)}
    assert {
        "recall20",
        "recall50",
        "coverage80",
        "hybrid_ce",
        "grounded_strict",
        "long_context",
        "sparse_splade",
    }.issubset(names)

    effective = payload.get("effective_defaults")
    assert isinstance(effective, dict)
    assert str(effective.get("production_profile") or "") == "hybrid_ce"


def test_retrieval_profiles_endpoint_omits_hidden_scope_fields() -> None:
    import app.api.v1.retrieval_profiles as api_mod

    payload = api_mod.get_retrieval_profiles()
    profiles = payload.get("profiles")
    assert isinstance(profiles, list)

    banned = {
        "tenant_id",
        "account_id",
        "dataset_id",
        "document_ids",
        "metadata_filter",
        "question",
        "query",
        "history",
    }
    for row in profiles:
        assert isinstance(row, dict)
        assert not (set(row.keys()) & banned)


def test_retrieval_profiles_endpoint_exposes_chat_default_profile_effective(monkeypatch) -> None:  # noqa: ANN001
    import app.api.v1.retrieval_profiles as api_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_DEFAULT_RETRIEVAL_PROFILE", "hybrid_ce", raising=False)
    payload = api_mod.get_retrieval_profiles()
    effective = payload.get("effective_defaults") or {}

    assert effective.get("chat_default_profile") == "hybrid_ce"
    chat_default_effective = effective.get("chat_default_effective") or {}
    assert chat_default_effective.get("retrieval_profile") == "hybrid_ce"
    assert str(chat_default_effective.get("retrieval_mode") or "") == "hybrid"


def test_retrieval_profiles_endpoint_exposes_profile_contract_metadata() -> None:
    import app.api.v1.retrieval_profiles as api_mod

    payload = api_mod.get_retrieval_profiles()
    profiles = payload.get("profiles") or []
    by_name = {
        str((row or {}).get("name") or ""): row
        for row in profiles
        if isinstance(row, dict)
    }

    grounded = by_name.get("grounded_strict") or {}
    assert grounded.get("retrieval_contract_mode") == "evidence_strict"
    assert grounded.get("visible_evidence_only") is True

    hybrid = by_name.get("hybrid_ce") or {}
    assert hybrid.get("retrieval_contract_mode") is None
    assert hybrid.get("visible_evidence_only") is False

    sparse = by_name.get("sparse_splade") or {}
    assert sparse.get("sparse_retrieval_enabled") is True
    assert sparse.get("sparse_retrieval_provider") == "splade"
