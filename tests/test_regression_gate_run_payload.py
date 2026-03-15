from __future__ import annotations

import importlib.util
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


def test_build_run_create_request_payload_includes_retrieval_overrides() -> None:
    mod = _load_module()

    payload = mod.build_run_create_request_payload(  # type: ignore[attr-defined]
        case_ids=["a", "b"],
        dataset_id="d",
        metrics=[],
        max_cases=2,
        retrieval_overrides={"retrieval_mode": "keyword", "top_k": 10, "score_threshold": 0.0},
    )
    assert payload["case_ids"] == ["a", "b"]
    assert payload["dataset_id"] == "d"
    assert payload["metrics"] == []
    assert payload["max_cases"] == 2
    assert payload["retrieval_mode"] == "keyword"
    assert payload["top_k"] == 10
    assert payload["score_threshold"] == pytest.approx(0.0)


def test_build_run_create_request_payload_omits_none_overrides() -> None:
    mod = _load_module()

    payload = mod.build_run_create_request_payload(  # type: ignore[attr-defined]
        case_ids=["a"],
        dataset_id="d",
        metrics=["faithfulness"],
        max_cases=1,
        retrieval_overrides={"retrieval_mode": None, "top_k": None, "score_threshold": None},
    )
    assert "retrieval_mode" not in payload
    assert "top_k" not in payload
    assert "score_threshold" not in payload


def test_build_run_create_request_payload_includes_extended_runtime_overrides() -> None:
    mod = _load_module()

    payload = mod.build_run_create_request_payload(  # type: ignore[attr-defined]
        case_ids=["a"],
        dataset_id="d",
        metrics=[],
        max_cases=1,
        retrieval_overrides={
            "retrieval_profile": "recall50",
            "enable_query_alias_expansion": True,
            "enable_multi_query": True,
            "multi_query_count": 4,
            "enable_query_rewrite": True,
            "query_rewrite_strategy": "kb_followup.v2",
            "query_rewrite_temperature": 0.3,
            "query_rewrite_max_chars": 180,
            "sparse_retrieval_enabled": True,
            "sparse_retrieval_provider": "splade",
            "fusion_strategy": "weighted",
            "fusion_budgets": {"vector": 20, "bm25": 10},
            "fusion_min_scores": {"vector": 0.2},
            "fusion_weights": {"vector": 0.7, "bm25": 0.3},
        },
    )
    assert payload["retrieval_profile"] == "recall50"
    assert payload["enable_query_alias_expansion"] is True
    assert payload["enable_multi_query"] is True
    assert payload["multi_query_count"] == 4
    assert payload["enable_query_rewrite"] is True
    assert payload["query_rewrite_strategy"] == "kb_followup.v2"
    assert payload["query_rewrite_temperature"] == pytest.approx(0.3)
    assert payload["query_rewrite_max_chars"] == 180
    assert payload["sparse_retrieval_enabled"] is True
    assert payload["sparse_retrieval_provider"] == "splade"
    assert payload["fusion_strategy"] == "weighted"
    assert payload["fusion_budgets"] == {"vector": 20, "bm25": 10}
    assert payload["fusion_min_scores"] == {"vector": 0.2}
    assert payload["fusion_weights"] == {"vector": 0.7, "bm25": 0.3}


def test_write_json_file_writes_trailing_newline(tmp_path: Path) -> None:
    mod = _load_module()

    out = tmp_path / "out.json"
    mod.write_json_file(out, {"a": 1})  # type: ignore[attr-defined]
    data = out.read_text(encoding="utf-8")
    assert data.endswith("\n")
