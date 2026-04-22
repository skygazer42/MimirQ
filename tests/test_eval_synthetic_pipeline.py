from __future__ import annotations

from app.rag.evaluation.synthetic.pipeline import generate_stage2_synthetic_dataset


def test_generate_stage2_synthetic_dataset_produces_file_ready_rows_and_manifest() -> None:
    seed_rows = [
        {
            "sample_id": "stage1-001",
            "query": "485 怎么配置？",
            "query_type": "factual",
            "source_type": "real_log",
            "gold_answer": "参考 RS-485 配置流程。",
            "gold_chunk_ids": ["chunk-485-config"],
            "is_unanswerable": False,
            "expected_route": "retrieval",
            "annotation_status": "labeled",
            "review_status": "reviewed",
        }
    ]

    dataset = generate_stage2_synthetic_dataset(seed_rows=seed_rows, target_count=2)

    assert len(dataset["rows"]) == 2
    assert all(row["source_type"] == "synthetic" for row in dataset["rows"])
    assert all(row["construction_method"] == "llm_generate" for row in dataset["rows"])
    assert dataset["manifest"]["sample_count"] == 2
    assert dataset["manifest"]["source_type_counts"] == {"synthetic": 2}
