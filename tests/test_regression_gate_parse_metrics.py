from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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


def test_parse_metrics_list_allows_empty_string() -> None:
    mod = _load_module()

    assert mod.parse_metrics_list("") == []  # type: ignore[attr-defined]
    assert mod.parse_metrics_list(" , , ") == []  # type: ignore[attr-defined]


def test_parse_metrics_list_trims_items() -> None:
    mod = _load_module()

    assert mod.parse_metrics_list("faithfulness,response_relevancy") == [  # type: ignore[attr-defined]
        "faithfulness",
        "response_relevancy",
    ]
    assert mod.parse_metrics_list("  faithfulness  , response_relevancy ") == [  # type: ignore[attr-defined]
        "faithfulness",
        "response_relevancy",
    ]

