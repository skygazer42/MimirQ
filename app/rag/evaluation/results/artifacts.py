from __future__ import annotations

from pathlib import Path


def build_eval_artifact_paths(*, root: Path, run_id: str) -> dict[str, Path]:
    base = Path(root) / str(run_id)
    return {
        "root": base,
        "results": base / "results.jsonl",
        "summary": base / "summary.json",
        "run_meta": base / "run_meta.json",
    }


__all__ = ["build_eval_artifact_paths"]
