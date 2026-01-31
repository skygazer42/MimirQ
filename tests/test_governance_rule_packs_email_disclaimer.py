from app.rag.preprocessing.cleaning import clean_markdown
from app.rag.preprocessing.rules import build_governance_rules


def test_governance_rule_pack_email_disclaimer_removes_common_email_disclaimer_lines():
    text = "\n".join(
        [
            "Hello team,",
            "Please review the attached proposal.",
            "",
            "This email and any attachments are intended only for the person or entity to which it is addressed",
            "and may contain confidential and/or privileged information.",
            "If you are not the intended recipient, please notify the sender immediately and delete this email.",
            "",
            "Thanks,",
            "Alice",
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
    assert "intended recipient" in baseline.markdown.lower()

    packed = clean_markdown(
        text,
        rules=build_governance_rules([], rule_packs=["email_disclaimer"]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "intended recipient" not in packed.markdown.lower()
    assert "confidential" not in packed.markdown.lower()
    assert "Hello team," in packed.markdown
    assert "Please review the attached proposal." in packed.markdown

