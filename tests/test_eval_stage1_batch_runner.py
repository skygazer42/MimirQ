from __future__ import annotations

from pathlib import Path

from app.rag.evaluation.runners.stage1_batch_runner import run_stage1_batch


def test_run_stage1_batch_writes_results_summary_and_run_meta(tmp_path: Path) -> None:
    sample_path = Path("/data/temp34/MimirQ/.worktrees/feat-backend/app/rag/evaluation/datasets/stage1/seed.jsonl")
    manifest_path = Path("/data/temp34/MimirQ/.worktrees/feat-backend/app/rag/evaluation/datasets/stage1/manifest.json")

    result = run_stage1_batch(
        sample_path=sample_path,
        manifest_path=manifest_path,
        output_root=tmp_path,
    )

    assert result["artifact_paths"]["results"].exists()
    assert result["artifact_paths"]["summary"].exists()
    assert result["artifact_paths"]["run_meta"].exists()
    assert result["summary"]["routes_evaluated"] == ["retrieval", "kg", "hybrid"]
    assert result["run_meta"]["routes"] == ["retrieval", "kg", "hybrid"]
