import json
from collections.abc import Callable, Iterable
from inspect import isawaitable
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.rag.evaluation.datasets.validator import validate_eval_dataset
from app.rag.evaluation.metrics.answer_det import evaluate_answer_deterministic
from app.rag.evaluation.metrics.retrieval import evaluate_retrieval_metrics
from app.rag.evaluation.reports.stage1_summary import summarize_stage1_results
from app.rag.evaluation.results.artifacts import build_eval_artifact_paths
from app.rag.evaluation.runners.base import build_runner_result
from app.rag.evaluation.runners.registry import EvaluationRunner, get_runner

RunnerResolver = Callable[[str], EvaluationRunner | None]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _chunk_ids(items: Iterable[Any]) -> list[str]:
    chunk_ids: dict[str, None] = {}
    for item in items or []:
        raw = item.get("chunk_id") if isinstance(item, dict) else item
        if raw is None:
            continue
        chunk_id = str(raw).strip()
        if chunk_id:
            chunk_ids[chunk_id] = None
    return list(chunk_ids)


async def run_stage1_batch(
    *,
    sample_path: Path,
    manifest_path: Path,
    output_root: Path,
    route_ids: list[str] | tuple[str, ...] | None = None,
    runner_resolver: RunnerResolver = get_runner,
) -> dict[str, Any]:
    rows = _load_jsonl(Path(sample_path))
    manifest = _load_json(Path(manifest_path))
    validation = validate_eval_dataset(rows=rows, manifest=manifest)
    if not validation["ok"]:
        raise ValueError(f"Stage1 dataset invalid: {validation['errors']}")

    run_id = uuid4().hex
    artifact_paths = build_eval_artifact_paths(root=Path(output_root), run_id=run_id)
    artifact_paths["root"].mkdir(parents=True, exist_ok=True)

    selected_route_ids = list(("retrieval", "kg", "hybrid") if route_ids is None else route_ids)
    detailed_rows: list[dict[str, Any]] = []
    for sample in validation["rows"]:
        for route_id in selected_route_ids:
            runner = runner_resolver(route_id)
            if runner is None:
                raise ValueError(f"Unknown evaluation route: {route_id!r}")
            route_result = runner(sample)
            if isawaitable(route_result):
                route_result = await route_result
            citations = list(route_result.get("citations") or [])
            cited_chunk_ids = _chunk_ids(citations)
            retrieved_items = route_result.get("retrieved_chunk_ids")
            retrieved_chunk_ids = (
                _chunk_ids(retrieved_items) if isinstance(retrieved_items, (list, tuple)) else list(cited_chunk_ids)
            )
            route_config = dict(route_result.get("route_config") or {})
            evaluators = {
                "answer_det": evaluate_answer_deterministic(
                    question=sample["query"],
                    answer=route_result["answer"]["text"],
                    gold_answer=sample["gold_answer"],
                    is_unanswerable=bool(sample.get("is_unanswerable")),
                ),
                "retrieval": evaluate_retrieval_metrics(
                    gold_chunk_ids=sample.get("gold_chunk_ids") or [],
                    retrieved_chunk_ids=retrieved_chunk_ids,
                    cited_chunk_ids=cited_chunk_ids,
                    recall_k=max(1, int(route_config.get("top_k") or 10)),
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
                    citations=citations,
                    latency_ms=route_result.get("latency_ms"),
                    token_cost=route_result.get("token_cost"),
                    route_config=route_config,
                    evaluators=evaluators,
                    agentic_iterations=route_result.get("agentic_iterations"),
                    agentic_latency_ms=route_result.get("agentic_latency_ms"),
                    agentic_token_cost=route_result.get("agentic_token_cost"),
                    agentic_status=route_result.get("agentic_status"),
                    extensions={**(route_result.get("extensions") or {}), "retrieved_chunk_ids": retrieved_chunk_ids},
                )
            )

    summary = summarize_stage1_results(detailed_rows)
    summary["routes_evaluated"] = list(selected_route_ids)
    run_meta = {
        "run_id": run_id,
        "schema_version": "mimirq.eval.run_meta.v1",
        "dataset_version": manifest.get("dataset_version"),
        "routes": selected_route_ids,
        "evaluators": ["answer_det", "retrieval"],
        "generated_at": manifest.get("generated_at"),
    }

    artifact_paths["results"].write_text(  # NOSONAR
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in detailed_rows),
        encoding="utf-8",
    )
    artifact_paths["summary"].write_text(  # NOSONAR
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    artifact_paths["run_meta"].write_text(  # NOSONAR
        json.dumps(run_meta, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )

    return {
        "artifact_paths": artifact_paths,
        "summary": summary,
        "run_meta": run_meta,
    }
