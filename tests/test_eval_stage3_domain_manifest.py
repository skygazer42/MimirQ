from __future__ import annotations

import json
from pathlib import Path

from app.rag.evaluation.datasets.validator import validate_eval_dataset


def test_stage3_domain_manifest_matches_domain_samples_and_includes_chunk_failure_taxonomy() -> None:
    root = Path("app/rag/evaluation/datasets/stage3_domain")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

    rows = []
    for name in ("finance", "legal", "support"):
        path = root / f"{name}.jsonl"
        rows.extend([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])

    result = validate_eval_dataset(rows=rows, manifest=manifest)

    assert result["ok"] is True
    assert manifest["dataset_name"] == "stage3-domain-chunk-failures"
    assert manifest["sample_count"] == len(rows)
    assert {tag for row in rows for tag in (row.get("tags") or [])} >= {
        "semantic_missing",
        "semantic_ambiguity",
        "structure_loss",
    }
