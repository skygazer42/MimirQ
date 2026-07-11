import json
from pathlib import Path

import pytest

from app.rag.evaluation.runners.hybrid_runner import run_hybrid_route
from app.rag.evaluation.runners.kg_runner import run_kg_route
from app.rag.evaluation.runners.retrieval_runner import run_retrieval_route
from app.rag.evaluation.runners.stage1_batch_runner import run_stage1_batch


def test_retrieval_runner_refuses_to_echo_gold_labels() -> None:
    sample = {
        "sample_id": "sample-1",
        "query": "真实问题",
        "gold_answer": "标准答案",
        "gold_chunk_ids": ["gold-chunk"],
    }

    with pytest.raises(RuntimeError, match="actual retrieval runner"):
        run_retrieval_route(sample)


def test_kg_runner_refuses_to_echo_gold_labels() -> None:
    sample = {
        "sample_id": "sample-1",
        "query": "真实问题",
        "gold_answer": "标准答案",
        "gold_chunk_ids": ["gold-chunk"],
    }

    with pytest.raises(RuntimeError, match="actual KG runner"):
        run_kg_route(sample)


def test_hybrid_runner_requires_actual_channel_rankings() -> None:
    sample = {
        "sample_id": "sample-1",
        "query": "真实问题",
        "gold_answer": "标准答案",
        "gold_chunk_ids": ["gold-chunk"],
    }

    with pytest.raises(RuntimeError, match="actual channel rankings"):
        run_hybrid_route(sample)


def test_hybrid_runner_does_not_turn_gold_labels_into_answer_or_citations() -> None:
    result = run_hybrid_route(
        {
            "sample_id": "sample-1",
            "query": "真实问题",
            "gold_answer": "标准答案",
            "gold_chunk_ids": ["gold-chunk"],
            "hybrid_channels": {
                "vector": ["gold-chunk", "vector-only"],
                "keyword": ["keyword-only", "gold-chunk"],
            },
        }
    )

    assert result["answer"]["text"] == ""
    assert result["citations"] == []
    assert "gold-chunk" in result["retrieved_chunk_ids"]


def test_stage1_batch_scores_retrieved_and_cited_ids_separately(tmp_path: Path) -> None:
    sample_path = tmp_path / "samples.jsonl"
    manifest_path = tmp_path / "manifest.json"
    sample_path.write_text(
        json.dumps(
            {
                "schema_version": "mimirq.eval.dataset.sample.v1",
                "sample_id": "sample-1",
                "query": "真实问题",
                "query_type": "factual",
                "source_type": "manual_seed",
                "gold_answer": "标准答案",
                "gold_chunk_ids": ["gold-chunk"],
                "gold_evidence": [],
                "is_unanswerable": False,
                "expected_route": "retrieval",
                "annotation_status": "labeled",
                "review_status": "approved",
                "tags": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "mimirq.eval.dataset.manifest.v1",
                "dataset_version": "test",
                "sample_count": 1,
                "query_type_counts": {"factual": 1},
                "source_type_counts": {"manual_seed": 1},
                "generated_at": "2026-07-11T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    def resolve_runner(route_id: str):
        if route_id != "retrieval":
            return None

        def run_actual(_sample):
            return {
                "actual_route": "retrieval",
                "answer": {"text": "模型答案"},
                "retrieved_chunk_ids": ["gold-chunk", "uncited-chunk"],
                "citations": [],
                "latency_ms": 12,
                "token_cost": 0,
                "route_config": {"top_k": 2},
            }

        return run_actual

    result = run_stage1_batch(
        sample_path=sample_path,
        manifest_path=manifest_path,
        output_root=tmp_path / "runs",
        route_ids=["retrieval"],
        runner_resolver=resolve_runner,
    )

    result_rows = [
        json.loads(line)
        for line in result["artifact_paths"]["results"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    retrieval_metrics = result_rows[0]["evaluators"]["retrieval"]
    assert retrieval_metrics["recall_at_k"] == 1.0
    assert retrieval_metrics["citation_coverage"] == 0.0
