from __future__ import annotations

from pathlib import Path

from app.rag.evaluation.results.artifacts import build_eval_artifact_paths


def test_build_eval_artifact_paths_returns_detail_summary_and_run_meta() -> None:
    paths = build_eval_artifact_paths(root=Path("/tmp/eval"), run_id="run-1")

    assert str(paths["results"]).endswith("run-1/results.jsonl")
    assert str(paths["summary"]).endswith("run-1/summary.json")
    assert str(paths["run_meta"]).endswith("run-1/run_meta.json")
