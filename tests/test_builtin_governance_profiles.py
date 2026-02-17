from __future__ import annotations


def test_builtin_governance_profiles_are_valid_and_unique():
    from app.api.schemas.document import DocumentPipelineOptions
    from app.services.governance_profiles import get_builtin_governance_profiles, validate_and_normalize_payload

    profiles = get_builtin_governance_profiles()
    keys = [p.key for p in profiles]

    # Keys should be unique and stable.
    assert len(keys) == len(set(keys))
    assert all(k.startswith("builtin:") for k in keys)

    # Ensure newly added profiles are present.
    for required in [
        "builtin:code_repo",
        "builtin:structured_data",
        "builtin:chat_exports",
        "builtin:metadata_enrich",
        "builtin:quality_gate_quarantine",
        "builtin:html_xpath_main",
    ]:
        assert required in keys

    # Ensure payload can be normalized and patched into pipeline options safely.
    for p in profiles:
        normalized = validate_and_normalize_payload(p.payload)
        assert normalized.version == "1"
        DocumentPipelineOptions(**(normalized.pipeline_patch or {}))


def test_policy_manual_profile_exists() -> None:
    from app.services.governance_profiles import get_builtin_governance_profiles

    keys = {p.key for p in get_builtin_governance_profiles()}
    assert "builtin:policy_manual_pdf" in keys
