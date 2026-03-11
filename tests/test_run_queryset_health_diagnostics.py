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


def test_run_queryset_health_diagnostics_writes_snapshot_and_history(tmp_path: Path) -> None:
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
