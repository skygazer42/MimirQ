from __future__ import annotations

import json
from pathlib import Path


def test_ci_retrieval_only_gate_has_hybrid_bounded_artifacts() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "sample_retrieval_bench.hybrid.json" in text
    assert "queryset_health.snapshot.hybrid.json" in text
    assert "queryset_health.history.hybrid.jsonl" in text
    assert "queryset_health.cron.hybrid.json" in text
    assert "queryset_health.diff.hybrid.json" in text
    assert "queryset_health.diff.hybrid.md" in text
    assert "--queryset-health-snapshot-hybrid" in text
    assert "--queryset-health-diff-hybrid" in text


def test_hybrid_retrieval_fixture_contract_is_valid() -> None:
    payload = json.loads(Path("data/sample/retrieval_fixture_hybrid_v1.json").read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.sample_retrieval_fixture.v1"
    defaults = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
    assert str(defaults.get("retrieval_mode") or "").strip().lower() == "hybrid"
    assert isinstance(payload.get("documents"), list)
    assert isinstance(payload.get("queries"), list)
