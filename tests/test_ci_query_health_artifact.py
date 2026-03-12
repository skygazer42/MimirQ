from __future__ import annotations

import json
from pathlib import Path


def test_ci_retrieval_only_gate_exports_queryset_health_diff_artifacts() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "scripts/diff_queryset_health_snapshots.py" in text
    assert "ci/queryset_health_snapshot_baseline.v1.json" in text
    assert "ci/queryset_health_snapshot_hybrid_baseline.v1.json" in text
    assert "artifacts/queryset_health.diff.json" in text
    assert "artifacts/queryset_health.diff.md" in text
    assert "artifacts/queryset_health.diff.hybrid.json" in text
    assert "artifacts/queryset_health.diff.hybrid.md" in text


def test_queryset_health_baseline_snapshot_contract_is_valid() -> None:
    payload = json.loads(Path("ci/queryset_health_snapshot_baseline.v1.json").read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.queryset_health_snapshot.v1"
    assert str(payload.get("policy_hash") or "").strip()
    assert str(payload.get("policy_source") or "").strip()
    assert isinstance(payload.get("metrics"), dict)
    assert isinstance((payload.get("risk") or {}).get("hard_cases"), list)


def test_queryset_health_hybrid_baseline_snapshot_contract_is_valid() -> None:
    payload = json.loads(Path("ci/queryset_health_snapshot_hybrid_baseline.v1.json").read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.queryset_health_snapshot.v1"
    assert str(payload.get("policy_hash") or "").strip()
    assert str(payload.get("policy_source") or "").strip()
    assert str(payload.get("retrieval_mode") or "").strip().lower() == "hybrid"
    assert isinstance(payload.get("metrics"), dict)
    assert isinstance((payload.get("risk") or {}).get("hard_cases"), list)
