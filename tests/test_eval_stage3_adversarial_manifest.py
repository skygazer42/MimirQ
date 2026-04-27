from __future__ import annotations

import json
from pathlib import Path

from app.rag.evaluation.datasets.validator import validate_eval_dataset


def test_stage3_adversarial_manifest_matches_rows_and_includes_target_taxonomy() -> None:
    root = Path("/data/temp34/MimirQ/.worktrees/feat-backend/app/rag/evaluation/datasets/stage3_adversarial")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

    rows = []
    for name in ("hard_negative", "prompt_injection", "pii_trap"):
        path = root / f"{name}.jsonl"
        rows.extend([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])

    result = validate_eval_dataset(rows=rows, manifest=manifest)

    assert result["ok"] is True
    assert manifest["dataset_name"] == "stage3-adversarial-guardrails"
    assert manifest["sample_count"] == len(rows)
    assert {tag for row in rows for tag in (row.get("tags") or [])} >= {
        "hard_negative",
        "prompt_injection",
        "pii_trap",
    }


def test_build_stage3_manifest_summarizes_query_and_source_counts() -> None:
    from app.rag.evaluation.datasets.stage3_manifest import build_stage3_manifest

    rows = [
        {"sample_id": "a", "query": "q1", "query_type": "multi_hop", "source_type": "synthetic"},
        {"sample_id": "b", "query": "q2", "query_type": "unanswerable", "source_type": "adversarial"},
        {"sample_id": "c", "query": "q3", "query_type": "unanswerable", "source_type": "adversarial"},
    ]

    manifest = build_stage3_manifest(
        dataset_name="stage3-adversarial-guardrails",
        rows=rows,
        dataset_version="2026.04.24",
        generated_at="2026-04-24T12:30:00Z",
    )

    assert manifest["schema_version"] == "mimirq.eval.dataset.manifest.v1"
    assert manifest["sample_count"] == 3
    assert manifest["query_type_counts"] == {"multi_hop": 1, "unanswerable": 2}
    assert manifest["source_type_counts"] == {"adversarial": 2, "synthetic": 1}
