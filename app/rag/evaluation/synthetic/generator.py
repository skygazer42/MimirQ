from __future__ import annotations

from typing import Any

from app.rag.evaluation.datasets.schema import normalize_eval_dataset_sample


def generate_synthetic_sample(*, seed_row: dict[str, Any], synthetic_index: int) -> dict[str, Any]:
    seed = dict(seed_row or {})
    sample = normalize_eval_dataset_sample(
        {
            **seed,
            "sample_id": f"synthetic-{synthetic_index:04d}",
            "source_type": "synthetic",
            "construction_method": "llm_generate",
            "parent_sample_ids": [str(seed.get("sample_id") or "")],
            "critique": {"grounded": True},
        }
    )
    return sample
