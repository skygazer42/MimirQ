from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "retrieval_ablation.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("retrieval_ablation", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_expand_param_grid_produces_stable_cartesian_product() -> None:
    mod = _load_module()

    combos = mod.expand_param_grid(  # type: ignore[attr-defined]
        {
            "top_k": [20, 50],
            "retrieval_mode": ["vector", "hybrid"],
        }
    )
    assert combos == [
        {"top_k": 20, "retrieval_mode": "vector"},
        {"top_k": 20, "retrieval_mode": "hybrid"},
        {"top_k": 50, "retrieval_mode": "vector"},
        {"top_k": 50, "retrieval_mode": "hybrid"},
    ]


def test_variant_label_from_params_is_deterministic() -> None:
    mod = _load_module()

    label = mod.variant_label_from_params(  # type: ignore[attr-defined]
        {"top_k": 20, "retrieval_mode": "vector"}
    )
    assert label == "top_k=20__retrieval_mode=vector"


def test_build_variant_plan_supports_explicit_variants_and_grid() -> None:
    mod = _load_module()

    base, variants = mod.build_variant_plan(  # type: ignore[attr-defined]
        {
            "base": {"label": "base", "rag_params": {"top_k": 20, "retrieval_mode": "hybrid"}},
            "variants": [{"label": "k50", "rag_params": {"top_k": 50}}],
            "grid": {"retrieval_mode": ["vector"]},
        }
    )

    assert base["label"] == "base"
    assert base["rag_params"]["top_k"] == 20

    labels = [v["label"] for v in variants]
    assert labels == ["k50", "retrieval_mode=vector"]

    k50 = variants[0]["rag_params"]
    assert k50["top_k"] == 50
    assert k50["retrieval_mode"] == "hybrid"

    vec = variants[1]["rag_params"]
    assert vec["top_k"] == 20
    assert vec["retrieval_mode"] == "vector"


def test_coerce_case_bundle_supports_bundle_and_legacy_shapes() -> None:
    mod = _load_module()

    ds, items = mod.coerce_case_bundle(  # type: ignore[attr-defined]
        {"dataset_id": "d", "items": [{"question": "q1"}]}
    )
    assert ds == "d"
    assert items == [{"question": "q1"}]

    ds2, items2 = mod.coerce_case_bundle(  # type: ignore[attr-defined]
        [{"dataset_id": "d", "question": "q1"}]
    )
    assert ds2 == "d"
    assert items2 == [{"question": "q1"}]


def test_safe_artifact_name_is_path_safe() -> None:
    mod = _load_module()

    assert mod.safe_artifact_name("k50") == "k50"  # type: ignore[attr-defined]
    assert mod.safe_artifact_name("a/b c") == "a_b_c"  # type: ignore[attr-defined]
