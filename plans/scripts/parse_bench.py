from __future__ import annotations

from typing import Any

_SCHEMA = "mimirq.parse_bench_plan.v1"
_DEFAULT_METRICS = ["accuracy", "latency_ms", "cost_usd"]


def _normalize_parsers(parsers: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in parsers or []:
        parser = str(item or "").strip().lower()
        if not parser:
            continue
        if parser in seen:
            continue
        seen.add(parser)
        out.append(parser)
    return out


def build_parse_bench_plan(
    *,
    parsers: list[str] | None = None,
    dataset: str,
    include_real_corpus: bool = False,
) -> dict[str, Any]:
    normalized_parsers = _normalize_parsers(parsers)
    dataset_name = str(dataset or "").strip()
    tracks = [dataset_name] if dataset_name else []
    if include_real_corpus:
        tracks.append("enterprise-corpus")

    return {
        "schema": _SCHEMA,
        "dataset": dataset_name,
        "tracks": tracks,
        "parsers": normalized_parsers,
        "metrics": list(_DEFAULT_METRICS),
    }


__all__ = ["build_parse_bench_plan"]
