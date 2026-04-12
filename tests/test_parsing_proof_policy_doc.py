from __future__ import annotations

from pathlib import Path


def test_parsing_proof_policy_doc_exists_and_mentions_baseline_and_gate_rules() -> None:
    text = Path("docs/guides/parsing_proof_policy.md").read_text(encoding="utf-8")
    assert "Parsing Proof Policy" in text
    assert "ci/parsing_retrieval_proof_summary_baseline.v1.json" in text
    assert "informational" in text.lower()
    assert "blocking" in text.lower()
    assert "gate.json" in text
    assert "diff.json" in text
    assert "16-case / 32-query" in text
    assert "query_count_total" in text
