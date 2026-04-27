from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_omnidocbench_runner_module():
    path = Path(__file__).resolve().parents[1] / "plans" / "scripts" / "omnidocbench_runner.py"
    spec = importlib.util.spec_from_file_location("omnidocbench_runner", str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_omnidocbench_runner_plan_defaults_to_public_track_and_three_parsers() -> None:
    mod = _load_omnidocbench_runner_module()
    out = mod.build_omnidocbench_runner_plan()

    assert out["schema"] == "mimirq.omnidocbench_runner_plan.v1"
    assert out["metrics"] == ["accuracy", "latency_ms", "cost_usd"]
    assert [row["parser_id"] for row in out["parsers"]] == ["deepdoc", "mineru25", "docling"]
    assert out["datasets"] == [
        {
            "dataset_id": "omnidocbench-public",
            "source": "huggingface",
            "uri": "hf://opendatalab/OmniDocBench",
            "download": True,
        }
    ]
    assert out["decision_gate"] == {
        "candidate": "deepdoc",
        "baseline": "mineru25",
        "action_if_accuracy_below_baseline": "switch_default_to_mineru25",
    }


def test_build_omnidocbench_runner_plan_supports_parser_and_internal_track_overrides() -> None:
    mod = _load_omnidocbench_runner_module()
    out = mod.build_omnidocbench_runner_plan(
        parsers=["docling", "deepdoc", "docling"],
        include_internal_real_docs=True,
    )

    assert [row["parser_id"] for row in out["parsers"]] == ["docling", "deepdoc"]
    assert out["datasets"] == [
        {
            "dataset_id": "omnidocbench-public",
            "source": "huggingface",
            "uri": "hf://opendatalab/OmniDocBench",
            "download": True,
        },
        {
            "dataset_id": "internal-real-docs",
            "source": "internal",
            "uri": "local://datasets/internal_real_docs",
            "download": False,
        },
    ]
