from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "eval_ltr_offline.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("eval_ltr_offline", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_eval_ltr_offline_build_eval_summary_includes_run_lineage() -> None:
    mod = _load_module()

    dataset_id = str(uuid.uuid4())
    cases_sha256 = "a" * 64
    pipeline_hashes = ["p" * 16]
    retrieval_cfg = {"schema": "mimirq.retrieval_config.v1", "hash": "b" * 32, "config": {"top_k": 50}}

    spec = mod.LTRFeatureSpec.v1()  # type: ignore[attr-defined]
    summary = mod.build_eval_summary(  # type: ignore[attr-defined]
        generated_at="2026-03-06T00:00:00Z",
        elapsed_sec=1.23,
        dataset_id=dataset_id,
        cases_total=10,
        cases_used=9,
        cases_sha256=cases_sha256,
        cases_schema="mimirq.regression_cases.v1",
        pipeline_hashes=pipeline_hashes,
        retrieval_config=retrieval_cfg,
        model_path="model.json",
        model_sha256="c" * 64,
        spec=spec,
        feature_spec_version=1,
        k=20,
        top_k=50,
        rerank_top_n=30,
        baseline={"hit": 0.1, "mrr": 0.2, "recall": 0.3, "ndcg": 0.4},
        ltr={"hit": 0.2, "mrr": 0.3, "recall": 0.4, "ndcg": 0.5},
    )

    assert summary["schema"] == "mimirq.ltr_offline_eval.v1"
    lineage = summary.get("lineage")
    assert isinstance(lineage, dict)
    assert lineage.get("schema") == "mimirq.ltr_run_lineage.v1"
    assert lineage.get("kind") == "eval"
    assert lineage.get("dataset_id") == dataset_id
    assert lineage.get("cases_sha256") == cases_sha256
    assert lineage.get("pipeline_hashes") == pipeline_hashes
    assert lineage.get("retrieval_config_hash") == retrieval_cfg["hash"]
    assert lineage.get("retrieval_config") == retrieval_cfg
    assert lineage.get("model_sha256") == "c" * 64

