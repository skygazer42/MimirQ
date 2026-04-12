from __future__ import annotations

from pathlib import Path


def test_parsing_proof_workflow_doc_mentions_sample_runner_and_artifacts() -> None:
    text = Path("docs/guides/parsing_proof_workflow.md").read_text(encoding="utf-8")
    assert "Parsing Proof Workflow" in text
    assert "make parsing-proof-sample" in text
    assert "runs/parsing_proof_broader_sample/summary.json" in text
    assert "runs/parsing_proof_broader_sample/gate.json" in text
    assert "runs/parsing_proof_broader_sample/diff.md" in text
    assert "tests/fixtures/parsing_golden_broader/manifest.json" in text
    assert "tests/fixtures/parsing_retrieval_proof/broader_case_queries.sample.json" in text
