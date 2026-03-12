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


def test_diff_queryset_health_snapshots_script_writes_json(tmp_path: Path) -> None:
    mod = _load_script("scripts/diff_queryset_health_snapshots.py")
    a = tmp_path / "baseline.json"
    b = tmp_path / "current.json"
    out = tmp_path / "diff.json"

    a.write_text(
        json.dumps(
            {
                "schema": "mimirq.queryset_health_snapshot.v1",
                "policy_hash": "aaaaaaaaaaaaaaaaaaaaaaaa",
                "policy_source": "policy_json",
                "metrics": {"hit_at_k": 0.8, "mrr": 0.5, "ndcg_at_k": 0.6, "p95_latency_ms": 10.0},
                "risk": {"miss_rate": 0.1, "weak_hit_rate": 0.2, "hard_cases": [{"id": "q-1"}]},
                "degradation_flags": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    b.write_text(
        json.dumps(
            {
                "schema": "mimirq.queryset_health_snapshot.v1",
                "policy_hash": "bbbbbbbbbbbbbbbbbbbbbbbb",
                "policy_source": "policy_json+cli_overrides",
                "metrics": {"hit_at_k": 0.7, "mrr": 0.45, "ndcg_at_k": 0.58, "p95_latency_ms": 12.0},
                "risk": {"miss_rate": 0.2, "weak_hit_rate": 0.3, "hard_cases": [{"id": "q-2"}]},
                "degradation_flags": ["mrr_drop"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(["--a", str(a), "--b", str(b), "--out", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.queryset_health_diff.v1"
    assert payload.get("policy", {}).get("changed") is True


def test_diff_queryset_health_snapshots_script_writes_markdown(tmp_path: Path) -> None:
    mod = _load_script("scripts/diff_queryset_health_snapshots.py")
    a = tmp_path / "baseline.json"
    b = tmp_path / "current.json"
    out_md = tmp_path / "diff.md"

    a.write_text(
        json.dumps(
            {
                "schema": "mimirq.queryset_health_snapshot.v1",
                "policy_hash": "aaaaaaaaaaaaaaaaaaaaaaaa",
                "policy_source": "policy_json",
                "metrics": {"hit_at_k": 0.8, "mrr": 0.5, "ndcg_at_k": 0.6, "p95_latency_ms": 10.0},
                "risk": {"miss_rate": 0.1, "weak_hit_rate": 0.2, "hard_cases": [{"id": "q-1"}]},
                "degradation_flags": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    b.write_text(
        json.dumps(
            {
                "schema": "mimirq.queryset_health_snapshot.v1",
                "policy_hash": "bbbbbbbbbbbbbbbbbbbbbbbb",
                "policy_source": "policy_json+cli_overrides",
                "metrics": {"hit_at_k": 0.7, "mrr": 0.45, "ndcg_at_k": 0.58, "p95_latency_ms": 12.0},
                "risk": {"miss_rate": 0.2, "weak_hit_rate": 0.3, "hard_cases": [{"id": "q-2"}]},
                "degradation_flags": ["mrr_drop"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(["--a", str(a), "--b", str(b), "--out-md", str(out_md)])
    assert rc == 0
    text = out_md.read_text(encoding="utf-8")
    assert "Queryset Health Snapshot Diff" in text
    assert "Policy/Hash Drift Summary" in text
    assert "Policy Changed" in text
    assert "Policy Hash Changed" in text
    assert "q-2" in text
