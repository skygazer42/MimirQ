from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_chunk_bench_module():
    path = Path(__file__).resolve().parents[1] / "plans" / "scripts" / "chunk_bench.py"
    spec = importlib.util.spec_from_file_location("chunk_bench", str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_chunk_bench_plan_emits_expected_schema_and_default_tracks() -> None:
    mod = _load_chunk_bench_module()
    out = mod.build_chunk_bench_plan()

    assert out["schema"] == "mimirq.chunk_bench_plan.v1"
    assert out["datasets"] == ["zh-enterprise", "legal", "tech-manual"]
    assert out["metrics"] == ["recall", "end_to_end_accuracy", "cost_usd"]
    config_ids = [row["config_id"] for row in out["configs"]]
    assert config_ids == ["fixed_512_128", "semantic", "contextual", "raptor"]


def test_build_chunk_bench_plan_supports_dataset_and_config_overrides() -> None:
    mod = _load_chunk_bench_module()
    out = mod.build_chunk_bench_plan(
        datasets=["finance", "legal", "finance"],
        config_ids=["semantic", "contextual", "semantic"],
    )

    assert out["datasets"] == ["finance", "legal"]
    assert [row["config_id"] for row in out["configs"]] == ["semantic", "contextual"]
