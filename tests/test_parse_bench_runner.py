from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_parse_bench_module():
    path = Path(__file__).resolve().parents[1] / "plans" / "scripts" / "parse_bench.py"
    spec = importlib.util.spec_from_file_location("parse_bench", str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_parse_bench_plan_lists_enabled_parsers_and_output_schema() -> None:
    mod = _load_parse_bench_module()
    out = mod.build_parse_bench_plan(
        parsers=["deepdoc", "mineru", "docling"],
        dataset="omnidocbench-mini",
    )

    assert out["schema"] == "mimirq.parse_bench_plan.v1"
    assert out["dataset"] == "omnidocbench-mini"
    assert out["parsers"] == ["deepdoc", "mineru", "docling"]
    assert out["metrics"] == ["accuracy", "latency_ms", "cost_usd"]


def test_build_parse_bench_plan_adds_default_real_corpus_track() -> None:
    mod = _load_parse_bench_module()
    out = mod.build_parse_bench_plan(
        parsers=["deepdoc", "mineru", "docling"],
        dataset="omnidocbench-mini",
        include_real_corpus=True,
    )

    assert out["tracks"] == ["omnidocbench-mini", "enterprise-corpus"]
