from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "generate_adaptive_router_policy.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("generate_adaptive_router_policy", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_policy_adds_recall_boost_when_quality_is_low() -> None:
    mod = _load_module()
    policy = mod.build_policy_from_benchmark_report(  # type: ignore[attr-defined]
        {
            "schema": "mimirq.sample_retrieval_benchmark.v1",
            "summary": {
                "hit_at_k": 0.5,
                "mrr": 0.3,
                "avg_latency_ms": 10.0,
                "p95_latency_ms": 20.0,
            },
        }
    )
    assert policy.get("schema") == "mimirq.adaptive_router_policy.v1"
    rules = list(policy.get("rules") or [])
    assert any(str(r.get("rule_id") or "") == "log_api_keyword_fastlane" for r in rules)
    assert any(str(r.get("rule_id") or "") == "faq_howto_recall_boost" for r in rules)
    assert "recall_boost" in list(policy.get("triggers") or [])


def test_main_writes_policy_file(tmp_path: Path) -> None:
    mod = _load_module()
    report = {
        "schema": "mimirq.sample_retrieval_benchmark.v1",
        "summary": {
            "hit_at_k": 0.95,
            "mrr": 0.9,
            "avg_latency_ms": 100.0,
            "p95_latency_ms": 120.0,
        },
    }
    report_path = tmp_path / "bench.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "adaptive_router_policy.v1.json"

    rc = mod.main(["--benchmark-report", str(report_path), "--out", str(out_path)])  # type: ignore[attr-defined]
    assert rc == 0
    assert out_path.exists()
    policy = json.loads(out_path.read_text(encoding="utf-8"))
    assert policy.get("schema") == "mimirq.adaptive_router_policy.v1"
    rules = list(policy.get("rules") or [])
    assert any(str(r.get("rule_id") or "") == "log_api_keyword_fastlane" for r in rules)
    assert any(str(r.get("rule_id") or "") == "long_query_cost_guard" for r in rules)
