from __future__ import annotations

from typing import Any

_SCHEMA = "mimirq.chunk_bench_plan.v1"
_DEFAULT_DATASETS = ["zh-enterprise", "legal", "tech-manual"]
_DEFAULT_METRICS = ["recall", "end_to_end_accuracy", "cost_usd"]
_CONFIG_LIBRARY = {
    "fixed_512_128": {
        "config_id": "fixed_512_128",
        "chunk_strategy": "langchain_recursive",
        "chunk_size": 512,
        "chunk_overlap": 128,
    },
    "semantic": {
        "config_id": "semantic",
        "chunk_strategy": "semantic_sentence",
    },
    "contextual": {
        "config_id": "contextual",
        "chunk_strategy": "contextual",
    },
    "raptor": {
        "config_id": "raptor",
        "chunk_strategy": "raptor",
    },
}


def _dedupe_strings(values: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def build_chunk_bench_plan(
    *,
    datasets: list[str] | None = None,
    config_ids: list[str] | None = None,
) -> dict[str, Any]:
    selected_datasets = _dedupe_strings(datasets or list(_DEFAULT_DATASETS))
    selected_config_ids = _dedupe_strings(config_ids or list(_CONFIG_LIBRARY.keys()))

    configs: list[dict[str, Any]] = []
    for config_id in selected_config_ids:
        key = str(config_id or "").strip()
        cfg = _CONFIG_LIBRARY.get(key)
        if not isinstance(cfg, dict):
            continue
        configs.append(dict(cfg))

    return {
        "schema": _SCHEMA,
        "datasets": selected_datasets,
        "configs": configs,
        "metrics": list(_DEFAULT_METRICS),
    }


__all__ = ["build_chunk_bench_plan"]
