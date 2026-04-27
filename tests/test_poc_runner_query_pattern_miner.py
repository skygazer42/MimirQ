from __future__ import annotations

from app.rag.evaluation.poc_runner.query_pattern_miner import mine_query_patterns


def test_mine_query_patterns_detects_abbreviations_multi_intent_and_glossary_candidates() -> None:
    summary = mine_query_patterns(
        [
            {
                "interaction_id": "q1",
                "original_query": "485 怎么配置？另外上次那个报错怎么处理？",
                "final_context_filenames": ["manual-a.pdf", "manual-b.pdf"],
            },
            {
                "interaction_id": "q2",
                "original_query": "485 没数据怎么办",
                "final_context_filenames": ["manual-a.pdf"],
            },
            {
                "interaction_id": "q3",
                "original_query": "485 通讯异常",
                "final_context_filenames": ["manual-a.pdf"],
            },
            {
                "interaction_id": "q4",
                "original_query": "485 参数设置步骤",
                "final_context_filenames": ["manual-c.pdf"],
            },
            {
                "interaction_id": "q5",
                "original_query": "485 驱动安装",
                "final_context_filenames": ["manual-a.pdf"],
            },
        ],
        abbreviation_min_frequency=5,
        top_k_keywords=5,
    )

    assert summary["abbreviations"][0]["token"] == "485"
    assert summary["glossary_candidates"][0]["token"] == "485"
    assert summary["multi_intent_queries"] == [
        {
            "interaction_id": "q1",
            "query": "485 怎么配置？另外上次那个报错怎么处理？",
            "signals": ["multiple_question_marks", "multi_intent_connector"],
        }
    ]
    assert summary["document_heat"][0] == {"filename": "manual-a.pdf", "count": 4}
    assert summary["keyword_scores"][0]["token"] == "485"
