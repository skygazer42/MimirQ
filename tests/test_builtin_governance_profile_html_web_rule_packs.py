from app.services.governance_profiles import get_builtin_governance_profiles


def test_builtin_governance_profile_html_web_uses_rule_packs():
    prof = next(p for p in get_builtin_governance_profiles() if p.key == "builtin:html_web")

    patch = dict(prof.payload.pipeline_patch or {})
    assert patch.get("governance_rule_packs") == ["web_navigation", "web_cookie_banners"]

    patterns = [str(r.pattern or "") for r in (prof.payload.regex_rules or [])]
    assert not any("skip to content" in p.lower() for p in patterns)
    assert not any("cookie" in p.lower() for p in patterns)

