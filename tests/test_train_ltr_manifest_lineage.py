from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "train_ltr_from_regression_cases.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("train_ltr_from_regression_cases", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_ltr_manifest_includes_versioned_run_lineage() -> None:
    mod = _load_module()

    dataset_id = str(uuid.uuid4())
    cases_sha256 = "a" * 64
    pipeline_hashes = ["p" * 16]
    retrieval_cfg = {"schema": "mimirq.retrieval_config.v1", "hash": "b" * 32, "config": {"top_k": 50}}

    spec = mod.LTRFeatureSpec.v1()  # type: ignore[attr-defined]
    manifest = mod.build_ltr_manifest(  # type: ignore[attr-defined]
        model_bytes=b"model-bytes",
        created_at="2026-03-06T00:00:00Z",
        model_file="model.json",
        spec=spec,
        feature_spec_version=1,
        objective="rank:pairwise",
        num_boost_round=10,
        seed=42,
        training={"rows_total": 1, "rows_pos": 1, "rows_neg": 0, "data_hash": "c" * 32},
        dataset_id=dataset_id,
        cases_sha256=cases_sha256,
        cases_schema="mimirq.regression_cases.v1",
        pipeline_hashes=pipeline_hashes,
        retrieval_config=retrieval_cfg,
        hard_negatives_sha256=None,
    )

    assert manifest["schema"] == "mimirq.ltr_model_manifest.v1"
    assert manifest["feature_schema"] == spec.schema
    assert manifest["feature_names"] == list(spec.feature_names)

    lineage = manifest.get("lineage")
    assert isinstance(lineage, dict)
    assert lineage.get("schema") == "mimirq.ltr_run_lineage.v1"
    assert lineage.get("dataset_id") == dataset_id
    assert lineage.get("cases_sha256") == cases_sha256
    assert lineage.get("cases_schema") == "mimirq.regression_cases.v1"
    assert lineage.get("pipeline_hashes") == pipeline_hashes
    assert lineage.get("retrieval_config_hash") == retrieval_cfg["hash"]
    assert lineage.get("retrieval_config") == retrieval_cfg

