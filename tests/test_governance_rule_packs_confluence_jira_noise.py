from app.rag.preprocessing.cleaning import clean_markdown
from app.rag.preprocessing.rules import build_governance_rules


def test_governance_rule_pack_confluence_jira_noise_removes_common_export_lines():
    text = "\n".join(
        [
            "Powered by Atlassian Confluence",
            "Created by Bob on Jan 1, 2025",
            "Last updated: 2025-01-02",
            "View in Confluence",
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
    assert "Atlassian Confluence" in baseline.markdown
    assert "Created by Bob" in baseline.markdown

    packed = clean_markdown(
        text,
        rules=build_governance_rules([], rule_packs=["confluence_jira_noise"]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "Atlassian Confluence" not in packed.markdown
    assert "Created by Bob" not in packed.markdown
    assert "Last updated" not in packed.markdown
    assert "View in Confluence" not in packed.markdown
    assert "# Title" in packed.markdown
    assert "Real content stays." in packed.markdown

