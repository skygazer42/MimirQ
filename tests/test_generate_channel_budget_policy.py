from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "generate_channel_budget_policy.py"


def _load_script_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("generate_channel_budget_policy", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_channel_budget_policy_enables_sparse_uplift_when_non_regressive() -> None:
    mod = _load_script_module()
    policy = mod.build_channel_budget_policy(  # type: ignore[attr-defined]
        benchmark_report={"top_k": 5, "summary": {"hit_at_k": 0.8, "mrr": 0.7, "p95_latency_ms": 120.0}},
        sparse_report={"summary": {"hit_at_k": 0.81, "mrr": 0.71, "p95_latency_ms": 130.0}},
    )

    assert policy.get("schema") == "mimirq.channel_budget_policy.v1"
    assert "sparse_uplift" in list(policy.get("triggers") or [])
    keyword = ((policy.get("profiles") or {}).get("keyword") or {})
    budgets = keyword.get("fusion_budgets") or {}
    assert int(budgets.get("sparse") or 0) >= 1


def test_main_writes_channel_budget_policy_file(tmp_path: Path) -> None:
    mod = _load_script_module()
    base = {"schema": "mimirq.sample_retrieval_benchmark.v1", "top_k": 5, "summary": {"hit_at_k": 1.0, "mrr": 1.0}}
    sparse = {"schema": "mimirq.sample_retrieval_benchmark.v1", "summary": {"hit_at_k": 1.0, "mrr": 1.0}}
    base_path = tmp_path / "bench.json"
    sparse_path = tmp_path / "sparse.json"
    out_path = tmp_path / "channel_budget_policy.v1.json"
    base_path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    sparse_path.write_text(json.dumps(sparse, ensure_ascii=False), encoding="utf-8")

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--benchmark-report",
            str(base_path),
            "--sparse-report",
            str(sparse_path),
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.channel_budget_policy.v1"
    assert isinstance((payload.get("profiles") or {}).get("keyword"), dict)


def test_orchestrator_policy_override_resolution_selects_profile_and_budgets() -> None:
    from app.rag.retrieval.orchestrator import resolve_channel_budget_policy_overrides

    overrides, meta = resolve_channel_budget_policy_overrides(
        policy={
            "schema": "mimirq.channel_budget_policy.v1",
            "fusion_strategy": "budgeted_rrf",
            "profiles": {
                "hybrid": {
                    "fusion_budgets": {"vector": 2, "bm25": 1, "lexical": 1, "sparse": 1},
                    "fusion_min_scores": {"sparse": 0.01},
                }
            },
        },
        retrieval_mode="hybrid",
        retrieval_profile=None,
    )

    assert meta.get("used") is True
    assert meta.get("selected_profile") == "hybrid"
    assert overrides.get("fusion_strategy") == "budgeted_rrf"
    budgets = overrides.get("fusion_budgets") or {}
    assert int(budgets.get("vector") or 0) == 2
    assert int(budgets.get("sparse") or 0) == 1
