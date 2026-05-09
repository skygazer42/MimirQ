from __future__ import annotations

from app.rag.feedback_loop.candidates import build_feedback_loop_candidates
from app.rag.industry_rules.schema import IndustryRuleset


def test_feedback_loop_batch_promotes_negative_feedback_to_hardneg_and_rule_candidates() -> None:
    rows = [
        {
            "feedback_id": "fb-neg-1",
            "rating": 1,
            "original_query": "MCU 没数据",
            "expected_answer": "请检查 MCU 通讯和采集配置。",
            "reference_sources": [{"chunk_id": "chunk-positive", "document_id": "doc-good"}],
            "retrieval_trace": {
                "retrieval": {"retrieval_config_hash": "cfg-1"},
                "citations": [
                    {"chunk_id": "chunk-hard", "document_id": "doc-bad"},
                    {"chunk_id": "chunk-positive", "document_id": "doc-good"},
                ],
            },
        },
        {
            "feedback_id": "fb-pos-1",
            "rating": 5,
            "original_query": "授权说明",
            "reference_sources": [{"chunk_id": "chunk-ok"}],
            "retrieval_trace": {"citations": [{"chunk_id": "chunk-ok"}]},
        },
    ]
    ruleset = IndustryRuleset(name="industrial_control", glossary={}, patterns=[], intents=[])

    out = build_feedback_loop_candidates(rows, ruleset=ruleset, max_rating=2, top_k=10)

    assert out["schema"] == "mimirq.feedback_loop_candidates.v1"
    assert out["summary"]["feedback_total"] == 2
    assert out["summary"]["negative_feedback_total"] == 1
    assert out["summary"]["hard_negative_records"] == 1
    assert out["summary"]["training_triples"] == 1

    hard = out["hard_negative_records"][0]
    assert hard["schema"] == "mimirq.hard_negatives.v1"
    assert hard["query_hash"]
    assert "MCU 没数据" not in str(hard)
    assert hard["hard_negatives"] == [{"chunk_id": "chunk-hard", "document_id": "doc-bad", "rank": 1}]
    assert hard["source_feedback_ids"] == ["fb-neg-1"]

    triple = out["training_triples"][0]
    assert triple["schema"] == "mimirq.feedback_training_triple.v1"
    assert triple["query_hash"] == hard["query_hash"]
    assert triple["positive_chunk_ids"] == ["chunk-positive"]
    assert triple["negative_chunk_ids"] == ["chunk-hard"]
    assert triple["source_feedback_id"] == "fb-neg-1"

    suggestions = out["rules_suggestions"]
    assert suggestions["schema"] == "mimirq.industry_rules_suggestions.v1"
    assert {item["token"] for item in suggestions["glossary_suggestions"]} >= {"MCU"}
