from app.rag.preprocessing.cleaning import clean_markdown
from app.rag.preprocessing.rules import build_governance_rules


def test_governance_rule_pack_web_navigation_removes_common_nav_lines():
    text = "\n".join(
        [
            "Skip to content",
            "Home / Docs / API",
            "Share this",
            "Back to top",
            "",
            "# Title",
            "Real content stays.",
        ]
    )

    baseline = clean_markdown(
        text,
        rules=build_governance_rules([]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "Skip to content" in baseline.markdown
    assert "Home / Docs / API" in baseline.markdown

    packed = clean_markdown(
        text,
        rules=build_governance_rules([], rule_packs=["web_navigation"]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )

    assert "Skip to content" not in packed.markdown
    assert "Home / Docs / API" not in packed.markdown
    assert "Share this" not in packed.markdown
    assert "Back to top" not in packed.markdown
    assert "# Title" in packed.markdown
    assert "Real content stays." in packed.markdown

