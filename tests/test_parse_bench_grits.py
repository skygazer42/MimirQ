from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_grits_module():
    path = Path(__file__).resolve().parents[1] / "app" / "rag" / "evaluation" / "parse_bench" / "grits.py"
    spec = importlib.util.spec_from_file_location("parse_bench_grits", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_compute_table_grits_is_1_for_perfect_match() -> None:
    mod = _load_grits_module()
    score = mod.compute_table_grits(
        pred_table=[["Quarter", "Revenue"], ["Q1", "100"]],
        gold_table=[["Quarter", "Revenue"], ["Q1", "100"]],
    )
    assert score["topology"] == 1.0
    assert score["content"] == 1.0
    assert score["f1"] == 1.0


def test_compute_table_grits_drops_when_shape_or_content_drifts() -> None:
    mod = _load_grits_module()
    score = mod.compute_table_grits(
        pred_table=[["Quarter", "Revenue", "Margin"], ["Q1", "100", "20%"]],
        gold_table=[["Quarter", "Revenue"], ["Q1", "100"]],
    )
    assert 0.0 < score["topology"] < 1.0
    assert 0.0 < score["content"] < 1.0
    assert 0.0 < score["f1"] < 1.0


def test_compute_table_collection_grits_returns_none_for_empty_inputs() -> None:
    mod = _load_grits_module()
    score = mod.compute_table_collection_grits(pred_tables=[], gold_tables=[])
    assert score == {"topology": None, "content": None, "f1": None}
