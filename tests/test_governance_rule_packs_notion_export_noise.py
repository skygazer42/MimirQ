from app.rag.preprocessing.cleaning import clean_markdown
from app.rag.preprocessing.rule_packs import GOVERNANCE_RULE_PACKS
from app.rag.preprocessing.rules import build_governance_rules


def test_notion_export_noise_removes_source_export_boilerplate():
    text = "\n".join(
        [
            "Exported from Notion",
            "Created time: 2026-05-20 10:00",
            "Last edited time: 2026-05-20 12:00",
            "",
            "# Weekly Ops Review",
            "真正的正文在这里。",
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
    assert "Exported from Notion" in baseline.markdown

    assert "notion_export_noise" in GOVERNANCE_RULE_PACKS
    packed = clean_markdown(
        text,
        rules=build_governance_rules([], rule_packs=["notion_export_noise"]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "Exported from Notion" not in packed.markdown
    assert "Created time" not in packed.markdown
    assert "Last edited time" not in packed.markdown
    assert "# Weekly Ops Review" in packed.markdown
    assert "真正的正文在这里。" in packed.markdown
