from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "seed_ci_retrieval_regression.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("seed_ci_retrieval_regression", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_cases_bundle_emits_regression_cases_v1_schema() -> None:
    mod = _load_module()

    bundle = mod.build_cases_bundle(  # type: ignore[attr-defined]
        {
            "dataset": {"id": "d"},
            "cases": [
                {
                    "question": "q1",
                    "reference_sources": [{"document_id": "doc", "chunk_id": "chunk"}],
                    "tags": ["ci"],
                }
            ],
        }
    )
    assert bundle["schema"] == "mimirq.regression_cases.v1"
    assert bundle["dataset_id"] == "d"
    assert bundle["items"][0]["question"] == "q1"

