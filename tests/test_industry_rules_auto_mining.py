from __future__ import annotations

from app.rag.industry_rules.mining.auto_rules import build_ruleset_suggestions
from app.rag.industry_rules.schema import IndustryRuleset


def test_build_ruleset_suggestions_emits_glossary_pattern_and_intent_candidates() -> None:
    rows = [
        {
            "interaction_id": "req-1",
            "original_query": "MCU 没数据",
            "final_context_filenames": ["manual-a.pdf"],
        },
        {
            "interaction_id": "req-2",
            "original_query": "授权失效了 怎么办",
            "final_context_filenames": ["license.docx"],
        },
        {
            "interaction_id": "req-3",
            "original_query": "KS 软件闪退，另外 485 也没数据",
            "final_context_filenames": ["ops.md"],
        },
    ]
    ruleset = IndustryRuleset(
        name="industrial_control",
        glossary={"485": ["RS-485"]},
        patterns=[],
        intents=[],
    )

    out = build_ruleset_suggestions(rows, ruleset=ruleset, top_k=10)

    assert out["schema"] == "mimirq.industry_rules_suggestions.v1"
    assert out["glossary_suggestions"][0]["token"] == "KS"
    assert {item["token"] for item in out["glossary_suggestions"]} >= {"KS", "MCU"}
    assert "485" not in {item["token"] for item in out["glossary_suggestions"]}

    pattern_keys = {item["pattern_key"] for item in out["pattern_suggestions"]}
    assert {"no_data", "licensing", "crash"}.issubset(pattern_keys)

    intent_names = {item["intent"] for item in out["intent_suggestions"]}
    assert {"fault_troubleshooting", "authorization"}.issubset(intent_names)

