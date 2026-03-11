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
    assert {"recall20", "recall50", "coverage80", "hybrid_ce"}.issubset(names)

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

