import pytest


def _p(*, extends=None, input_formats=None, pipeline_patch=None, regex_rules=None, processing_scripts=None):
    from app.api.schemas.governance_profile import GovernanceProfilePayload

    return GovernanceProfilePayload(
        version="1",
        extends=extends,
        input_formats=input_formats or ["markdown"],
        pipeline_patch=pipeline_patch or {},
        regex_rules=regex_rules or [],
        processing_scripts=processing_scripts or [],
    )


def _rule(pat: str):
    from app.api.schemas.governance_profile import RegexRuleModel

    return RegexRuleModel(pattern=pat, repl="", flags=0)


def test_governance_profile_inheritance_merges_patch_and_rules():
    from app.api.schemas.governance_profile import GovernanceProfileOut
    from app.services.governance_profiles_resolver import resolve_profile_inheritance

    base = GovernanceProfileOut(
        id=None,
        key="builtin:base",
        name="Base",
        description=None,
        is_system=True,
        payload=_p(
            input_formats=["markdown"],
            pipeline_patch={"governance_enabled": True, "governance_remove_noise_lines": True},
            regex_rules=[_rule("base")],
            processing_scripts=[
                {
                    "name": "base.py",
                    "language": "python",
                    "stage": "post_governance",
                    "content": "def transform(text):\n    return text\n",
                    "enabled": False,
                }
            ],
        ),
        created_at=None,
        updated_at=None,
    )

    child = GovernanceProfileOut(
        id=None,
        key="builtin:child",
        name="Child",
        description=None,
        is_system=True,
        payload=_p(
            extends="builtin:base",
            input_formats=["html", "markdown"],
            pipeline_patch={"governance_remove_noise_lines": False, "governance_remove_boilerplate": True},
            regex_rules=[_rule("child")],
            processing_scripts=[
                {
                    "name": "child.ts",
                    "language": "typescript",
                    "stage": "post_parse",
                    "content": "export const transform = (text: string) => text\n",
                    "enabled": False,
                }
            ],
        ),
        created_at=None,
        updated_at=None,
    )

    by_ref = {
        "builtin:base": base,
        "builtin:child": child,
    }

    resolved = resolve_profile_inheritance(child, fetch_by_ref=lambda ref: by_ref[ref])

    assert [c.key for c in resolved.chain] == ["builtin:base", "builtin:child"]
    assert resolved.effective.pipeline_patch["governance_enabled"] is True
    assert resolved.effective.pipeline_patch["governance_remove_noise_lines"] is False
    assert resolved.effective.pipeline_patch["governance_remove_boilerplate"] is True
    assert [r.pattern for r in resolved.effective.regex_rules] == ["base", "child"]
    assert [s.name for s in resolved.effective.processing_scripts] == ["base.py", "child.ts"]
    assert resolved.effective.input_formats == ["markdown", "html"]


def test_governance_profile_inheritance_detects_cycle():
    from app.api.schemas.governance_profile import GovernanceProfileOut
    from app.services.governance_profiles_resolver import resolve_profile_inheritance

    a = GovernanceProfileOut(
        id=None,
        key="builtin:a",
        name="A",
        description=None,
        is_system=True,
        payload=_p(extends="builtin:b"),
        created_at=None,
        updated_at=None,
    )
    b = GovernanceProfileOut(
        id=None,
        key="builtin:b",
        name="B",
        description=None,
        is_system=True,
        payload=_p(extends="builtin:a"),
        created_at=None,
        updated_at=None,
    )

    by_ref = {"builtin:a": a, "builtin:b": b}

    with pytest.raises(ValueError):
        resolve_profile_inheritance(a, fetch_by_ref=lambda ref: by_ref[ref], max_depth=10)
