from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script(rel: str):
    path = _repo_root() / rel
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_run_queryset_health_diagnostics_writes_snapshot_and_history(tmp_path: Path, capsys) -> None:
    mod = _load_script("scripts/run_queryset_health_diagnostics.py")
    bench = tmp_path / "bench.json"
    out = tmp_path / "snapshot.json"
    hist = tmp_path / "history.jsonl"

    bench.write_text(
        json.dumps(
            {
                "schema": "mimirq.sample_retrieval_benchmark.v1",
                "fixture_hash": "fixture-1",
                "retrieval_mode": "keyword",
                "top_k": 5,
                "summary": {
                    "cases_total": 10,
                    "hit_at_k": 0.8,
                    "mrr": 0.6,
                    "ndcg_at_k": 0.7,
                    "avg_latency_ms": 8.0,
                    "p95_latency_ms": 15.0,
                },
                "cases": [
                    {
                        "id": "q-1",
                        "question": "alpha",
                        "hit_at_k": 0.0,
                        "reciprocal_rank": 0.0,
                        "ndcg_at_k": 0.0,
                        "latency_ms": 8.5,
                    },
                    {
                        "id": "q-2",
                        "question": "beta",
                        "hit_at_k": 1.0,
                        "reciprocal_rank": 0.2,
                        "ndcg_at_k": 0.3,
                        "latency_ms": 7.8,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(
        [
            "--benchmark-report",
            str(bench),
            "--out",
            str(out),
            "--history",
            str(hist),
            "--profile-hash",
            "profile-abc",
            "--cron",
        ]
    )
    assert rc == 0
    assert out.exists()
    assert hist.exists()

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.queryset_health_snapshot.v1"
    assert payload.get("profile_hash") == "profile-abc"
    assert payload.get("policy_source") == "default"
    assert len(str(payload.get("policy_hash") or "")) == 24
    assert payload.get("risk", {}).get("miss_count") == 1
    assert payload.get("risk", {}).get("weak_hit_count") == 1

    cron_line = capsys.readouterr().out.strip()
    cron_payload = json.loads(cron_line)
    assert cron_payload.get("policy_source") == "default"
    assert len(str(cron_payload.get("policy_hash") or "")) == 24
    assert cron_payload.get("policy_changed") is False
    assert cron_payload.get("miss_rate") == 0.5
    assert cron_payload.get("weak_hit_rate") == 0.5
    assert cron_payload.get("hard_case_ids") == ["q-1", "q-2"]


def test_run_queryset_health_diagnostics_applies_cli_risk_threshold_overrides(tmp_path: Path) -> None:
    mod = _load_script("scripts/run_queryset_health_diagnostics.py")
    bench_baseline = tmp_path / "bench_baseline.json"
    bench_regressed = tmp_path / "bench_regressed.json"
    out = tmp_path / "snapshot.json"
    hist = tmp_path / "history.jsonl"
    policy = tmp_path / "policy.json"

    policy.write_text(
        json.dumps(
            {
                "miss_rate_regression_threshold": 0.6,
                "weak_hit_rr_threshold": 0.15,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    bench_baseline.write_text(
        json.dumps(
            {
                "schema": "mimirq.sample_retrieval_benchmark.v1",
                "fixture_hash": "fixture-2",
                "retrieval_mode": "keyword",
                "top_k": 5,
                "summary": {
                    "cases_total": 2,
                    "hit_at_k": 1.0,
                    "mrr": 1.0,
                    "ndcg_at_k": 1.0,
                    "avg_latency_ms": 5.0,
                    "p95_latency_ms": 6.0,
                },
                "cases": [
                    {
                        "id": "q-a",
                        "question": "baseline a",
                        "hit_at_k": 1.0,
                        "reciprocal_rank": 1.0,
                        "ndcg_at_k": 1.0,
                        "latency_ms": 4.0,
                    },
                    {
                        "id": "q-b",
                        "question": "baseline b",
                        "hit_at_k": 1.0,
                        "reciprocal_rank": 1.0,
                        "ndcg_at_k": 1.0,
                        "latency_ms": 6.0,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc1 = mod.main(
        [
            "--benchmark-report",
            str(bench_baseline),
            "--out",
            str(out),
            "--history",
            str(hist),
            "--profile-hash",
            "profile-def",
            "--policy-json",
            str(policy),
        ]
    )
    assert rc1 == 0

    bench_regressed.write_text(
        json.dumps(
            {
                "schema": "mimirq.sample_retrieval_benchmark.v1",
                "fixture_hash": "fixture-2",
                "retrieval_mode": "keyword",
                "top_k": 5,
                "summary": {
                    "cases_total": 2,
                    "hit_at_k": 0.5,
                    "mrr": 0.1,
                    "ndcg_at_k": 0.2,
                    "avg_latency_ms": 5.0,
                    "p95_latency_ms": 6.0,
                },
                "cases": [
                    {
                        "id": "q-a",
                        "question": "regressed miss",
                        "hit_at_k": 0.0,
                        "reciprocal_rank": 0.0,
                        "ndcg_at_k": 0.0,
                        "latency_ms": 7.0,
                    },
                    {
                        "id": "q-b",
                        "question": "regressed weak",
                        "hit_at_k": 1.0,
                        "reciprocal_rank": 0.2,
                        "ndcg_at_k": 0.4,
                        "latency_ms": 5.0,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc2 = mod.main(
        [
            "--benchmark-report",
            str(bench_regressed),
            "--out",
            str(out),
            "--history",
            str(hist),
            "--profile-hash",
            "profile-def",
            "--policy-json",
            str(policy),
            "--miss-rate-regression-threshold",
            "0.7",
        ]
    )
    assert rc2 == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("policy_source") == "policy_json+cli_overrides"
    assert len(str(payload.get("policy_hash") or "")) == 24
    assert payload.get("trend", {}).get("policy_changed") is True
    assert payload.get("risk", {}).get("miss_rate") == 0.5
    # Policy file lowered weak-hit threshold to 0.15, so rr=0.2 is not weak.
    assert payload.get("risk", {}).get("weak_hit_count") == 0
    # CLI override disables miss-rate regression for this run.
    assert "miss_rate_regression" not in (payload.get("degradation_flags") or [])
