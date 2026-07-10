
from typing import Any

_SCHEMA = "mimirq.omnidocbench_runner_plan.v1"
_DEFAULT_METRICS = ["accuracy", "latency_ms", "cost_usd"]
_DEFAULT_PARSERS = ["deepdoc", "mineru25", "docling"]
_PARSER_LIBRARY = {
    "deepdoc": {"parser_id": "deepdoc", "backend": "deepdoc", "profile": "default"},
    "mineru25": {"parser_id": "mineru25", "backend": "mineru", "profile": "v2_5"},
    "docling": {"parser_id": "docling", "backend": "docling", "profile": "default"},
}
_PUBLIC_DATASET = {
    "dataset_id": "omnidocbench-public",
    "source": "huggingface",
    "uri": "hf://opendatalab/OmniDocBench",
    "download": True,
}
_INTERNAL_DATASET = {
    "dataset_id": "internal-real-docs",
    "source": "internal",
    "uri": "local://datasets/internal_real_docs",
    "download": False,
}
_DECISION_GATE = {
    "candidate": "deepdoc",
    "baseline": "mineru25",
    "action_if_accuracy_below_baseline": "switch_default_to_mineru25",
}


def _dedupe_strings(values: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw or "").strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def build_omnidocbench_runner_plan(
    *,
    parsers: list[str] | None = None,
    include_internal_real_docs: bool = False,
) -> dict[str, Any]:
    selected_parser_ids = _dedupe_strings(parsers or list(_DEFAULT_PARSERS))
    parser_specs: list[dict[str, Any]] = []
    for parser_id in selected_parser_ids:
        spec = _PARSER_LIBRARY.get(parser_id)
        if not isinstance(spec, dict):
            continue
        parser_specs.append(dict(spec))

    datasets = [dict(_PUBLIC_DATASET)]
    if include_internal_real_docs:
        datasets.append(dict(_INTERNAL_DATASET))

    return {
        "schema": _SCHEMA,
        "datasets": datasets,
        "parsers": parser_specs,
        "metrics": list(_DEFAULT_METRICS),
        "report": {
            "columns": ["parser_id", "accuracy", "latency_ms", "cost_usd"],
            "sort_by": ["accuracy:desc", "latency_ms:asc", "cost_usd:asc"],
        },
        "decision_gate": dict(_DECISION_GATE),
    }


__all__ = ["build_omnidocbench_runner_plan"]
