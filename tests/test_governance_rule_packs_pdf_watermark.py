from app.rag.preprocessing.cleaning import clean_markdown
from app.rag.preprocessing.rules import build_governance_rules


def test_governance_rule_pack_pdf_watermark_removes_common_watermark_lines():
    text = "\n".join(
        [
            "DRAFT",
            "Company Confidential",
            "仅供内部使用",
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
    assert "DRAFT" in baseline.markdown
    assert "Company Confidential" in baseline.markdown
    assert "仅供内部使用" in baseline.markdown

    packed = clean_markdown(
        text,
        rules=build_governance_rules([], rule_packs=["pdf_watermark"]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "DRAFT" not in packed.markdown
    assert "Company Confidential" not in packed.markdown
    assert "仅供内部使用" not in packed.markdown
    assert "# Title" in packed.markdown
    assert "Real content stays." in packed.markdown

