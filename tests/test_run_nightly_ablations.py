from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "run_nightly_ablations.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("run_nightly_ablations", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_default_ablations_include_hybrid_rerank_variant() -> None:
    mod = _load_module()

    ablations = mod._default_ablations()  # type: ignore[attr-defined]
    assert isinstance(ablations, list) and ablations

    assert any(
        (ab.get("rag_params") or {}).get("retrieval_mode") == "hybrid"
        and bool((ab.get("rag_params") or {}).get("enable_reranker"))
        for ab in ablations
    )
