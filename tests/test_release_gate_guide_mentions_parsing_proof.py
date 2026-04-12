from __future__ import annotations

from pathlib import Path


def test_release_gate_guide_mentions_parsing_proof_artifacts_and_flags() -> None:
    text = Path("docs/guides/release_gate.md").read_text(encoding="utf-8")
    assert "parsing-proof" in text.lower()
    assert "artifacts/parsing_proof_broader_sample/summary.json" in text
    assert "artifacts/parsing_proof_broader_sample/diff.json" in text
    assert "query_count_total" in text
    assert "case_family_counts" in text
    assert "case_category_counts" in text
    assert "--parsing-proof-summary" in text
    assert "--parsing-proof-diff" in text
