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


def test_generate_stage2_synthetic_dataset_filters_rejected_samples_and_tracks_stats() -> None:
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

    calls = {"n": 0}

    def _generate(*, seed_row, synthetic_index):  # noqa: ANN001
        calls["n"] += 1
        return {
            **seed_row,
            "sample_id": f"synthetic-{synthetic_index:04d}",
            "query": f"q-{synthetic_index}",
            "query_type": "factual" if synthetic_index % 2 else "multi_hop",
            "source_type": "synthetic",
            "gold_answer": "a",
            "gold_chunk_ids": ["c1"],
            "annotation_status": "labeled",
            "review_status": "pending",
            "construction_method": "llm_generate",
            "parent_sample_ids": [seed_row["sample_id"]],
            "critique": {},
        }

    def _critique(sample):  # noqa: ANN001
        sample = dict(sample)
        if sample["sample_id"].endswith("0001"):
            sample["critique"] = {"grounded": True, "relevance": False, "standalone": True}
        else:
            sample["critique"] = {"grounded": True, "relevance": True, "standalone": True}
        return sample

    dataset = generate_stage2_synthetic_dataset(
        seed_rows=seed_rows,
        target_count=2,
        generator_fn=_generate,
        critic_fn=_critique,
        max_attempts=4,
    )

    assert calls["n"] == 3
    assert [row["sample_id"] for row in dataset["rows"]] == ["synthetic-0002", "synthetic-0003"]
    assert dataset["summary"]["attempted"] == 3
    assert dataset["summary"]["accepted"] == 2
    assert dataset["summary"]["rejected"] == 1
    assert dataset["summary"]["rejection_reasons"] == {"relevance": 1}
    assert dataset["manifest"]["sample_count"] == 2
    assert dataset["manifest"]["query_type_counts"] == {"factual": 1, "multi_hop": 1}
    critique_summary = dataset["manifest"]["critique_summary"]
    assert critique_summary["accepted"] == 2
    assert critique_summary["rejected"] == 1
