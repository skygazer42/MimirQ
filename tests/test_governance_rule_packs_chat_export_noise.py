from app.rag.preprocessing.cleaning import clean_markdown
from app.rag.preprocessing.rules import build_governance_rules


def test_governance_rule_pack_chat_export_noise_removes_export_shell_lines():
    text = "\n".join(
        [
            "Slack Export",
            "2026-05-20",
            "10:42 AM",
            "View in Slack",
            "Reply in thread",
            "Alice has joined the channel",
            "",
            "Incident summary:",
            "Queue latency increased after the deploy.",
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
    assert "Slack Export" in baseline.markdown

    packed = clean_markdown(
        text,
        rules=build_governance_rules([], rule_packs=["chat_export_noise"]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "Slack Export" not in packed.markdown
    assert "View in Slack" not in packed.markdown
    assert "Reply in thread" not in packed.markdown
    assert "joined the channel" not in packed.markdown
    assert "Incident summary:" in packed.markdown
    assert "Queue latency increased after the deploy." in packed.markdown
