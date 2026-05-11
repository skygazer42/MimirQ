from __future__ import annotations

import json
from pathlib import Path


def test_stage1_manifest_matches_seed_file_counts() -> None:
    root = Path("app/rag/evaluation/datasets/stage1")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (root / "seed.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    assert manifest["dataset_name"] == "stage1-seed"
    assert manifest["sample_count"] == len(rows)
    assert set(manifest["query_type_counts"]) == {"factual", "structured", "multi_hop", "unanswerable"}
    assert set(manifest["source_type_counts"]) >= {"real_log", "manual_seed", "adversarial"}
