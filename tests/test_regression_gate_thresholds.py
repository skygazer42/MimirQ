from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "regression_gate.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("regression_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_normalize_thresholds_supports_min_and_max() -> None:
    mod = _load_module()

    out = mod.normalize_thresholds(  # type: ignore[attr-defined]
        {
            "faithfulness": 0.7,
            "abstain_rate": {"max": 0.02},
            "retrieval_recall": {"min": 0.3, "max": 0.9},
        }
    )
    assert out["faithfulness"] == {"min": 0.7}
    assert out["abstain_rate"] == {"max": 0.02}
    assert out["retrieval_recall"] == {"min": 0.3, "max": 0.9}


def test_check_thresholds_enforces_min_and_max() -> None:
    mod = _load_module()

    thresholds = mod.normalize_thresholds(  # type: ignore[attr-defined]
        {
            "faithfulness": 0.7,
            "abstain_rate": {"max": 0.02},
        }
    )

    ok, failures = mod.check_thresholds(  # type: ignore[attr-defined]
        summary={"faithfulness": 0.8, "abstain_rate": 0.03},
        thresholds=thresholds,
    )
    assert ok is False
    assert any("abstain_rate" in str(msg) for msg in (failures or []))


def test_parse_thresholds_config_supports_structured_format_with_slices() -> None:
    mod = _load_module()

    metrics, slices = mod.parse_thresholds_config(  # type: ignore[attr-defined]
        {
            "schema": "mimirq.thresholds.v2",
            "dataset_id": "00000000-0000-0000-0000-000000000000",
            "metrics": {"faithfulness": 0.7, "abstain_rate": {"max": 0.02}},
            "slices": {
                "file_type": {
                    "pdf": {"retrieval_recall": {"min": 0.3}},
                }
            },
        }
    )
    assert metrics["faithfulness"] == {"min": 0.7}
    assert metrics["abstain_rate"] == {"max": 0.02}
    assert slices["file_type"]["pdf"]["retrieval_recall"] == {"min": 0.3}


def test_check_thresholds_enforces_slice_thresholds() -> None:
    mod = _load_module()

    metrics, slices = mod.parse_thresholds_config(  # type: ignore[attr-defined]
        {
            "metrics": {"retrieval_recall": {"min": 0.5}},
            "slices": {
                "file_type": {"pdf": {"retrieval_recall": {"min": 0.8}}},
            },
        }
    )

    ok, failures = mod.check_thresholds(  # type: ignore[attr-defined]
        summary={
            "retrieval_recall": 0.9,
            "retrieval_slices": {
                "file_type": {
                    "buckets": [
                        {"key": "pdf", "items": 10, "retrieval_recall": 0.7},
                    ]
                }
            },
        },
        thresholds=metrics,
        slice_thresholds=slices,
    )
    assert ok is False
    assert any("slice[file_type=pdf]" in str(msg) for msg in (failures or []))


def test_check_thresholds_supports_multihop_metrics() -> None:
    mod = _load_module()

    thresholds = mod.normalize_thresholds(  # type: ignore[attr-defined]
        {
            "multihop_path_completeness": {"min": 0.7},
            "multihop_order_consistency": {"min": 0.6},
        }
    )
    ok, failures = mod.check_thresholds(  # type: ignore[attr-defined]
        summary={
            "multihop_path_completeness": 0.8,
            "multihop_order_consistency": 0.5,
        },
        thresholds=thresholds,
    )
    assert ok is False
    assert any("multihop_order_consistency" in str(msg) for msg in (failures or []))


def test_generate_thresholds_from_summary_includes_top_and_slice_bounds() -> None:
    mod = _load_module()

    cfg = mod.generate_thresholds_from_summary(  # type: ignore[attr-defined]
        dataset_id="d",
        summary={
            "items": 10,
            "retrieval_recall": 0.8,
            "abstain_rate": 0.1,
            "retrieval_slices": {
                "file_type": {
                    "buckets": [
                        {"key": "pdf", "items": 10, "retrieval_recall": 0.8, "abstain_rate": 0.1},
                        {"key": "md", "items": 1, "retrieval_recall": 1.0, "abstain_rate": 0.0},
                    ]
                }
            },
        },
        metrics=["retrieval_recall", "abstain_rate"],
        slice_dims=["file_type"],
        slice_metrics=["retrieval_recall", "abstain_rate"],
        rel_drop=0.10,
        abs_slack=0.02,
        min_slice_items=5,
    )
    assert cfg["schema"] == "mimirq.thresholds.v2"
    assert cfg["dataset_id"] == "d"
    assert cfg["metrics"]["retrieval_recall"]["min"] == pytest.approx(0.72)
    assert cfg["metrics"]["abstain_rate"]["max"] == pytest.approx(0.12)
    # Only include buckets with enough items.
    assert "pdf" in cfg["slices"]["file_type"]
    assert "md" not in cfg["slices"]["file_type"]


def test_generate_thresholds_from_summary_preserves_plugin_case_source_without_run_ids() -> None:
    mod = _load_module()

    cfg = mod.generate_thresholds_from_summary(  # type: ignore[attr-defined]
        dataset_id="d",
        summary={
            "items": 2,
            "expected_metadata_hit_rate": 1.0,
            "expected_metadata_recall": 1.0,
        },
        metrics=["expected_metadata_hit_rate", "expected_metadata_recall"],
        case_source={
            "kind": "plugin_golden",
            "plugin_ref": "plugin:demo-service@1.0.0:chunk",
            "plugin_id": "demo-service",
            "plugin_version": "1.0.0",
            "plugin_package_hash": "pkg_hash_abc123",
            "draft_items_total": 2,
            "import_result": {
                "created": 2,
                "updated": 0,
                "case_ids": ["case-a", "case-b"],
            },
        },
    )

    assert cfg["case_source"] == {
        "kind": "plugin_golden",
        "plugin_ref": "plugin:demo-service@1.0.0:chunk",
        "plugin_id": "demo-service",
        "plugin_version": "1.0.0",
        "plugin_package_hash": "pkg_hash_abc123",
        "draft_items_total": 2,
    }
    assert "import_result" not in cfg["case_source"]
    assert "case_ids" not in json.dumps(cfg["case_source"], ensure_ascii=False)


def test_default_threshold_generation_includes_plugin_expected_metadata_metrics() -> None:
    mod = _load_module()

    parser = mod.build_arg_parser()  # type: ignore[attr-defined]
    args = parser.parse_args(["--cases", "cases.json"])

    assert "expected_metadata_hit_rate" in mod.parse_metrics_list(args.gen_metrics)  # type: ignore[attr-defined]
    assert "expected_metadata_recall" in mod.parse_metrics_list(args.gen_metrics)  # type: ignore[attr-defined]
    assert "expected_metadata_hit_rate" in mod.parse_metrics_list(args.gen_slice_metrics)  # type: ignore[attr-defined]
    assert "expected_metadata_recall" in mod.parse_metrics_list(args.gen_slice_metrics)  # type: ignore[attr-defined]


def test_empty_metrics_is_allowed_for_threshold_generation_without_gate() -> None:
    mod = _load_module()

    assert mod.is_empty_metrics_allowed(  # type: ignore[attr-defined]
        metrics=[],
        thresholds={},
        slice_thresholds={},
        thresholds_file_provided=False,
        generate_thresholds_out="out.json",
    )

    assert (
        mod.is_empty_metrics_allowed(  # type: ignore[attr-defined]
            metrics=[],
            thresholds={},
            slice_thresholds={},
            thresholds_file_provided=False,
            generate_thresholds_out="",
        )
        is False
    )

    assert mod.is_empty_metrics_allowed(  # type: ignore[attr-defined]
        metrics=[],
        thresholds={"retrieval_recall": {"min": 0.3}},
        slice_thresholds={},
        thresholds_file_provided=True,
        generate_thresholds_out="",
    )


def test_format_unified_diff_includes_headers_and_changes() -> None:
    mod = _load_module()

    diff = mod.format_unified_diff(  # type: ignore[attr-defined]
        "a\n",
        "b\n",
        fromfile="old.json",
        tofile="new.json",
    )
    assert "--- old.json" in diff
    assert "+++ new.json" in diff
    assert "-a" in diff
    assert "+b" in diff
