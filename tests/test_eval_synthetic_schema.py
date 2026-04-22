from __future__ import annotations

from app.rag.evaluation.datasets.schema import normalize_eval_dataset_sample
from app.rag.evaluation.datasets.validator import validate_eval_dataset


def test_synthetic_sample_schema_accepts_synthetic_source_and_generation_metadata() -> None:
    sample = normalize_eval_dataset_sample(
        {
            "sample_id": "syn-1",
            "query": "根据通讯日志和 schema，如何判断 485 掉线原因？",
            "query_type": "multi_hop",
            "source_type": "synthetic",
            "gold_answer": "需要结合日志与 schema 字段定位原因。",
            "gold_chunk_ids": ["chunk-a", "chunk-b"],
            "is_unanswerable": False,
            "expected_route": "hybrid",
            "annotation_status": "labeled",
            "review_status": "pending",
            "construction_method": "llm_generate",
            "parent_sample_ids": ["stage1-001"],
            "critique": {"grounded": True},
        }
    )

    assert sample["source_type"] == "synthetic"
    assert sample["construction_method"] == "llm_generate"
    assert sample["parent_sample_ids"] == ["stage1-001"]
    assert sample["critique"] == {"grounded": True}


def test_validate_eval_dataset_accepts_manifest_with_synthetic_counts() -> None:
    rows = [
        {
            "schema_version": "mimirq.eval.dataset.sample.v1",
            "sample_id": "syn-1",
            "query": "test",
            "query_type": "multi_hop",
            "source_type": "synthetic",
            "gold_answer": "answer",
            "gold_chunk_ids": ["c1"],
            "gold_evidence": [],
            "is_unanswerable": False,
            "expected_route": "hybrid",
            "annotation_status": "labeled",
            "review_status": "pending",
            "construction_method": "llm_generate",
            "parent_sample_ids": ["stage1-001"],
            "critique": {"grounded": True},
        }
    ]
    manifest = {
        "dataset_name": "stage2-synthetic",
        "schema_version": "mimirq.eval.dataset.manifest.v1",
        "dataset_version": "2026.04.23",
        "sample_count": 1,
        "source_type_counts": {"synthetic": 1},
        "query_type_counts": {"multi_hop": 1},
        "generated_at": "2026-04-23T12:00:00Z",
    }

    result = validate_eval_dataset(rows=rows, manifest=manifest)
    assert result["ok"] is True
