from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.rag.evaluation.synthetic.critic import critique_synthetic_sample
from app.rag.evaluation.synthetic.generator import generate_synthetic_sample


def generate_stage2_synthetic_dataset(*, seed_rows: list[dict[str, Any]], target_count: int) -> dict[str, Any]:
    generated: list[dict[str, Any]] = []
    seeds = list(seed_rows or [])
    if not seeds:
        return {
            "rows": [],
            "manifest": {
                "dataset_name": "stage2-synthetic",
                "schema_version": "mimirq.eval.dataset.manifest.v1",
                "dataset_version": datetime.now(UTC).strftime("%Y.%m.%d"),
                "sample_count": 0,
                "source_type_counts": {},
                "query_type_counts": {},
                "generated_at": datetime.now(UTC).isoformat(),
            },
        }

    target = max(0, int(target_count or 0))
    for idx in range(target):
        seed = seeds[idx % len(seeds)]
        sample = generate_synthetic_sample(seed_row=seed, synthetic_index=idx + 1)
        sample = critique_synthetic_sample(sample)
        generated.append(sample)

    query_counts = Counter(str(row.get("query_type") or "") for row in generated)
    source_counts = Counter(str(row.get("source_type") or "") for row in generated)
    manifest = {
        "dataset_name": "stage2-synthetic",
        "schema_version": "mimirq.eval.dataset.manifest.v1",
        "dataset_version": datetime.now(UTC).strftime("%Y.%m.%d"),
        "sample_count": len(generated),
        "source_type_counts": dict(source_counts),
        "query_type_counts": dict(query_counts),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    return {"rows": generated, "manifest": manifest}
