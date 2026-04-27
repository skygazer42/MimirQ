from __future__ import annotations

from app.rag.evaluation.datasets.validator import validate_eval_dataset


def test_validate_eval_dataset_accepts_valid_stage1_seed_and_manifest() -> None:
    rows = [
        {
            "schema_version": "mimirq.eval.dataset.sample.v1",
            "sample_id": "s1",
            "query": "485 怎么配置？",
            "query_type": "factual",
            "source_type": "real_log",
            "gold_answer": "A",
            "gold_chunk_ids": ["chunk-1"],
            "is_unanswerable": False,
            "expected_route": "retrieval",
            "annotation_status": "labeled",
            "review_status": "pending",
        },
        {
            "schema_version": "mimirq.eval.dataset.sample.v1",
            "sample_id": "s2",
            "query": "X9 新型号怎么接线？",
            "query_type": "unanswerable",
            "source_type": "manual_seed",
            "gold_answer": "",
            "gold_chunk_ids": [],
            "is_unanswerable": True,
            "expected_route": None,
            "annotation_status": "labeled",
            "review_status": "reviewed",
        },
    ]
    manifest = {
        "dataset_name": "stage1-seed",
        "schema_version": "mimirq.eval.dataset.manifest.v1",
        "dataset_version": "2026.04.22",
        "sample_count": 2,
        "source_type_counts": {"real_log": 1, "manual_seed": 1},
        "query_type_counts": {"factual": 1, "unanswerable": 1},
        "generated_at": "2026-04-22T12:00:00Z",
    }

    result = validate_eval_dataset(rows=rows, manifest=manifest)

    assert result["ok"] is True
    assert result["errors"] == []


def test_validate_eval_dataset_rejects_invalid_enum_values() -> None:
    rows = [
        {
            "schema_version": "mimirq.eval.dataset.sample.v1",
            "sample_id": "bad",
            "query": "bad",
            "query_type": "summary",
            "source_type": "unknown",
            "gold_answer": "x",
            "gold_chunk_ids": [],
            "is_unanswerable": False,
            "annotation_status": "todo",
            "review_status": "nope",
        }
    ]
    manifest = {
        "dataset_name": "stage1-seed",
        "schema_version": "mimirq.eval.dataset.manifest.v1",
        "dataset_version": "2026.04.22",
        "sample_count": 1,
        "source_type_counts": {"unknown": 1},
        "query_type_counts": {"summary": 1},
        "generated_at": "2026-04-22T12:00:00Z",
    }

    result = validate_eval_dataset(rows=rows, manifest=manifest)

    assert result["ok"] is False
    assert any("query_type" in err for err in result["errors"])
    assert any("source_type" in err for err in result["errors"])
