from app.rag.preprocessing.cleaning import clean_markdown
from app.rag.preprocessing.rules import build_governance_rules


def test_governance_rule_pack_web_cookie_banners_removes_cookie_banner_lines():
    text = "\n".join(
        [
            "Cookie Consent",
            "We use cookies to improve your experience on our site.",
            "Accept cookies",
            "",
            "# Title",
            "Real content stays.",
        ]
    )

    # Default rules should NOT remove cookie-banner text.
    baseline = clean_markdown(
        text,
        rules=build_governance_rules([]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "Cookie Consent" in baseline.markdown

    # Rule pack should remove typical cookie-banner lines (optional pack; default off).
    packed = clean_markdown(
        text,
        rules=build_governance_rules([], rule_packs=["web_cookie_banners"]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "Cookie Consent" not in packed.markdown
    assert "cookies" not in packed.markdown.lower()
    assert "# Title" in packed.markdown
    assert "Real content stays." in packed.markdown

