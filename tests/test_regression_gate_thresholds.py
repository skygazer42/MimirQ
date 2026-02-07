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

