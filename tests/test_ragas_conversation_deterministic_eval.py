from __future__ import annotations


def test_conversation_deterministic_scores_alias_ui_metrics() -> None:
    from app.rag.evaluation import ragas as mod

    scores = mod._build_conversation_deterministic_scores(
        user_input="武进区台湾通行证在哪里办理",
        response="武进区办理地点是常州市武进区湖塘镇花园街1号。",
        retrieved_contexts=["答案要点：办理地点：常州市武进区湖塘镇花园街1号。"],
    )

    assert scores["faithfulness"] == scores["faithfulness_det"]
    assert scores["response_relevancy"] == scores["response_relevancy_det"]
    assert scores["faithfulness"] is not None
    assert scores["response_relevancy"] > 0
