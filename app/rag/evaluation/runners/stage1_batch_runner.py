from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.rag.evaluation.datasets.validator import validate_eval_dataset
from app.rag.evaluation.metrics.answer_det import evaluate_answer_deterministic
from app.rag.evaluation.metrics.retrieval import evaluate_retrieval_metrics
from app.rag.evaluation.results.artifacts import build_eval_artifact_paths
from app.rag.evaluation.runners.base import build_runner_result
from app.rag.evaluation.runners.registry import get_runner
from app.rag.evaluation.reports.stage1_summary import summarize_stage1_results


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def run_stage1_batch(*, sample_path: Path, manifest_path: Path, output_root: Path) -> dict[str, Any]:
    rows = _load_jsonl(Path(sample_path))
    manifest = _load_json(Path(manifest_path))
    validation = validate_eval_dataset(rows=rows, manifest=manifest)
    if not validation["ok"]:
        raise ValueError(f"Stage1 dataset invalid: {validation['errors']}")

    run_id = uuid4().hex
    artifact_paths = build_eval_artifact_paths(root=Path(output_root), run_id=run_id)
    artifact_paths["root"].mkdir(parents=True, exist_ok=True)

    route_ids = ["retrieval", "kg", "hybrid"]
    detailed_rows: list[dict[str, Any]] = []
    for sample in validation["rows"]:
        for route_id in route_ids:
            runner = get_runner(route_id)
            if runner is None:
                continue
            route_result = runner(sample)
            evaluators = {
                "answer_det": evaluate_answer_deterministic(
                    question=sample["query"],
                    answer=(route_result.get("answer") or {}).get("text") or "",
                    gold_answer=sample["gold_answer"],
                    is_unanswerable=bool(sample.get("is_unanswerable")),
                ),
                "retrieval": evaluate_retrieval_metrics(
                    gold_chunk_ids=sample.get("gold_chunk_ids") or [],
                    retrieved_chunk_ids=[item.get("chunk_id") for item in (route_result.get("citations") or [])],
                    cited_chunk_ids=[item.get("chunk_id") for item in (route_result.get("citations") or [])],
                    recall_k=10,
                ),
            }
            detailed_rows.append(
                build_runner_result(
                    sample_id=sample["sample_id"],
                    route_id=route_id,
                    query_type=sample["query_type"],
                    source_type=sample["source_type"],
                    expected_route=sample.get("expected_route"),
                    actual_route=route_result.get("actual_route"),
                    answer=route_result.get("answer"),
                    citations=route_result.get("citations"),
                    latency_ms=route_result.get("latency_ms"),
                    token_cost=route_result.get("token_cost"),
                    route_config=route_result.get("route_config"),
                    evaluators=evaluators,
                )
            )

    summary = summarize_stage1_results(detailed_rows)
    summary["routes_evaluated"] = list(route_ids)
    run_meta = {
        "run_id": run_id,
        "schema_version": "mimirq.eval.run_meta.v1",
        "dataset_version": manifest.get("dataset_version"),
        "routes": route_ids,
        "evaluators": ["answer_det", "retrieval"],
        "generated_at": manifest.get("generated_at"),
    }

    artifact_paths["results"].write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in detailed_rows),
        encoding="utf-8",
    )
    artifact_paths["summary"].write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    artifact_paths["run_meta"].write_text(json.dumps(run_meta, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "artifact_paths": artifact_paths,
        "summary": summary,
        "run_meta": run_meta,
    }
