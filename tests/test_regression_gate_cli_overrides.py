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


def test_regression_gate_cli_builds_extended_retrieval_overrides() -> None:
    """
    CLI should expose key runtime knobs so hourly/nightly gates can match production.
    """
    mod = _load_module()

    parser = mod.build_arg_parser()  # type: ignore[attr-defined]
    args = parser.parse_args(
        [
            "--cases",
            "cases.json",
            "--retrieval-profile",
            "recall50",
            "--fusion-strategy",
            "rrf",
            "--enable-sparse-retrieval",
            "--sparse-retrieval-provider",
            "splade",
            "--enable-query-rewrite",
            "--enable-multi-query",
            "--disable-reranker",
            "--reranker-provider",
            "none",
            "--reranker-top-n",
            "10",
        ]
    )

    overrides = mod.build_retrieval_overrides_from_args(args)  # type: ignore[attr-defined]
    assert overrides["retrieval_profile"] == "recall50"
    assert overrides["fusion_strategy"] == "rrf"
    assert overrides["sparse_retrieval_enabled"] is True
    assert overrides["sparse_retrieval_provider"] == "splade"
    assert overrides["enable_query_rewrite"] is True
    assert overrides["enable_multi_query"] is True
    assert overrides["enable_reranker"] is False
    assert overrides["reranker_provider"] == "none"
    assert overrides["reranker_top_n"] == 10


def test_regression_gate_normalize_run_overrides_accepts_known_keys() -> None:
    mod = _load_module()
    out = mod.normalize_run_overrides(  # type: ignore[attr-defined]
        {
            "top_k": 30,
            "retrieval_mode": "hybrid",
            "enable_reranker": False,
            "reranker_provider": "none",
            "reranker_top_n": 10,
        }
    )
    assert out["top_k"] == 30
    assert out["retrieval_mode"] == "hybrid"
    assert out["enable_reranker"] is False
    assert out["reranker_provider"] == "none"
    assert out["reranker_top_n"] == 10


def test_regression_gate_normalize_run_overrides_rejects_unknown_keys() -> None:
    mod = _load_module()
    with pytest.raises(ValueError):
        mod.normalize_run_overrides({"not_a_real_key": 1})  # type: ignore[attr-defined]


def test_regression_gate_run_overrides_merge_prefers_cli_flags() -> None:
    mod = _load_module()
    parser = mod.build_arg_parser()  # type: ignore[attr-defined]
    args = parser.parse_args(["--cases", "cases.json", "--top-k", "50"])

    file_overrides = mod.normalize_run_overrides({"top_k": 30})  # type: ignore[attr-defined]
    cli_overrides = mod.build_retrieval_overrides_from_args(args)  # type: ignore[attr-defined]
    merged = {**file_overrides, **cli_overrides}
    assert merged["top_k"] == 50
