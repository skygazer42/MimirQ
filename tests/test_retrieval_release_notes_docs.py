from __future__ import annotations

from pathlib import Path


def test_changelog_contains_retrieval_quality_block() -> None:
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    assert "### Retrieval Quality" in changelog
    assert "hit@10" in changelog
    assert "mrr@10" in changelog
    assert "ndcg@10" in changelog


def test_retrieval_release_notes_guide_exists_and_mentions_artifacts() -> None:
    text = Path("docs/guides/retrieval_release_notes.md").read_text(encoding="utf-8")
    assert "leaderboard.json" in text
    assert "gate_report.json" in text
    assert "thresholds.v2.json" in text
