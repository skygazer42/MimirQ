from __future__ import annotations

from pathlib import Path


def test_operations_docs_mentions_queryset_policy_metadata() -> None:
    text = Path("docs/operations.md").read_text(encoding="utf-8").lower()
    assert "policy_hash" in text
    assert "policy_source" in text
    assert "policy_changed" in text


def test_scripts_readme_mentions_queryset_policy_changed_signal() -> None:
    text = Path("scripts/README.md").read_text(encoding="utf-8").lower()
    assert "policy_hash" in text
    assert "policy_source" in text
    assert "policy_changed" in text


def test_scripts_readme_mentions_queryset_health_diff_script() -> None:
    text = Path("scripts/README.md").read_text(encoding="utf-8")
    assert "diff_queryset_health_snapshots.py" in text
