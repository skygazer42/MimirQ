from __future__ import annotations

from pathlib import Path


def test_release_gate_docs_mentions_queryset_policy_metadata() -> None:
    text = Path("docs/guides/release_gate.md").read_text(encoding="utf-8").lower()
    assert "--queryset-health-snapshot" in text
    assert "policy_hash" in text
    assert "policy_source" in text
    assert "policy_changed" in text
