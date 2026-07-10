
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.rag.evaluation.synthetic.critic import critique_synthetic_sample, should_keep_synthetic_sample
from app.rag.evaluation.synthetic.generator import generate_synthetic_sample


def generate_stage2_synthetic_dataset(
    *,
    seed_rows: list[dict[str, Any]],
    target_count: int,
    generator_fn=generate_synthetic_sample,
    critic_fn=critique_synthetic_sample,
    max_attempts: int | None = None,
) -> dict[str, Any]:
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
                "critique_summary": {"attempted": 0, "accepted": 0, "rejected": 0, "rejection_reasons": {}},
                "generated_at": datetime.now(UTC).isoformat(),
            },
            "summary": {"attempted": 0, "accepted": 0, "rejected": 0, "rejection_reasons": {}},
        }

    target = max(0, int(target_count or 0))
    attempts_limit = max(target, int(max_attempts or max(target * 3, target)))
    attempted = 0
    rejection_reasons: Counter[str] = Counter()

    idx = 0
    while len(generated) < target and attempted < attempts_limit:
        seed = seeds[idx % len(seeds)]
        synthetic_index = attempted + 1
        sample = generator_fn(seed_row=seed, synthetic_index=synthetic_index)
        sample = critic_fn(sample)
        attempted += 1
        idx += 1

        keep, failures = should_keep_synthetic_sample(sample)
        if not keep:
            for reason in failures:
                rejection_reasons[str(reason)] += 1
            continue
        generated.append(sample)

    query_counts = Counter(str(row.get("query_type") or "") for row in generated)
    source_counts = Counter(str(row.get("source_type") or "") for row in generated)
    critique_summary = {
        "attempted": int(attempted),
        "accepted": int(len(generated)),
        "rejected": int(max(0, attempted - len(generated))),
        "rejection_reasons": dict(sorted(rejection_reasons.items(), key=lambda kv: kv[0])),
    }
    manifest = {
        "dataset_name": "stage2-synthetic",
        "schema_version": "mimirq.eval.dataset.manifest.v1",
        "dataset_version": datetime.now(UTC).strftime("%Y.%m.%d"),
        "sample_count": len(generated),
        "source_type_counts": dict(source_counts),
        "query_type_counts": dict(query_counts),
        "critique_summary": critique_summary,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    return {"rows": generated, "manifest": manifest, "summary": critique_summary}
