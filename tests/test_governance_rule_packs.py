from __future__ import annotations

from app.rag.preprocessing.rule_packs import GOVERNANCE_RULE_PACKS, list_governance_rule_packs
from app.rag.preprocessing.rules import build_governance_rules


def test_list_governance_rule_packs_includes_new_packs():  # noqa: ANN001
    packs = list_governance_rule_packs()
    assert "wechat_mp_noise" in packs
    assert "pdf_header_footer_cn" in packs
    assert "notion_export_noise" in packs


def test_build_governance_rules_expands_rule_packs():  # noqa: ANN001
    for key in ["wechat_mp_noise", "pdf_header_footer_cn", "notion_export_noise"]:
        rules = build_governance_rules(rule_packs=[key])
        patterns = {r.pattern for r in rules}
        for rr in GOVERNANCE_RULE_PACKS[key]:
            assert rr.pattern in patterns

