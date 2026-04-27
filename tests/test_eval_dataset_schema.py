from __future__ import annotations

from app.rag.evaluation.datasets.schema import (
    EVAL_DATASET_SCHEMA_V1,
    normalize_eval_dataset_sample,
)


def test_normalize_eval_dataset_sample_keeps_required_stage1_fields() -> None:
    sample = normalize_eval_dataset_sample(
        {
            "sample_id": "s1",
            "query": "485 怎么配置？",
            "query_type": "factual",
            "source_type": "real_log",
            "gold_answer": "参考 RS-485 配置流程。",
            "gold_chunk_ids": ["chunk-1"],
            "is_unanswerable": False,
            "expected_route": "retrieval",
            "annotation_status": "labeled",
            "review_status": "pending",
        }
    )

    assert sample["schema_version"] == EVAL_DATASET_SCHEMA_V1
    assert sample["sample_id"] == "s1"
    assert sample["query_type"] == "factual"
    assert sample["source_type"] == "real_log"
    assert sample["gold_chunk_ids"] == ["chunk-1"]
    assert sample["expected_route"] == "retrieval"
    assert sample["annotation_status"] == "labeled"
    assert sample["review_status"] == "pending"
