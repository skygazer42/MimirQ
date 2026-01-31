import pytest


def test_governance_profile_payload_rejects_unknown_pipeline_keys():
    from app.api.schemas.governance_profile import GovernanceProfilePayload
    from app.services.governance_profiles import validate_and_normalize_payload

    payload = GovernanceProfilePayload(
        version="1",
        input_formats=["markdown"],
        pipeline_patch={"totally_unknown_key": True},
        regex_rules=[],
    )

    with pytest.raises(ValueError):
        validate_and_normalize_payload(payload)


def test_governance_profile_payload_rejects_suspicious_regex():
    from app.api.schemas.governance_profile import GovernanceProfilePayload
    from app.services.governance_profiles import validate_and_normalize_payload

    payload = GovernanceProfilePayload(
        version="1",
        input_formats=["markdown"],
        pipeline_patch={"governance_enabled": True},
        regex_rules=[{"pattern": "(.*)+", "repl": "", "flags": 0}],
    )

    with pytest.raises(ValueError):
        validate_and_normalize_payload(payload)


def test_governance_profile_payload_normalizes_extends_ref():
    from app.api.schemas.governance_profile import GovernanceProfilePayload
    from app.services.governance_profiles import validate_and_normalize_payload

    payload = GovernanceProfilePayload(
        version="1",
        extends="  builtin:kb_default  ",
        input_formats=["markdown"],
        pipeline_patch={"governance_enabled": True},
        regex_rules=[],
    )

    out = validate_and_normalize_payload(payload)
    assert out.extends == "builtin:kb_default"


def test_governance_profile_payload_rejects_extends_with_control_chars():
    from app.api.schemas.governance_profile import GovernanceProfilePayload
    from app.services.governance_profiles import validate_and_normalize_payload

    payload = GovernanceProfilePayload(
        version="1",
        extends="builtin:kb_default\x00",
        input_formats=["markdown"],
        pipeline_patch={"governance_enabled": True},
        regex_rules=[],
    )

    with pytest.raises(ValueError):
        validate_and_normalize_payload(payload)
