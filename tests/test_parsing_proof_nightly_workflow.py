from __future__ import annotations

from pathlib import Path


def test_parsing_proof_nightly_workflow_exists_and_wires_sample_runner() -> None:
    text = Path(".github/workflows/parsing-proof-nightly.yml").read_text(encoding="utf-8")
    assert "Parsing Proof Nightly" in text
    assert "workflow_dispatch" in text
    assert "schedule" in text
    assert "cron:" in text
    assert "parsing-proof-nightly" in text
    assert "run_sample_parsing_retrieval_proof.py" in text
    assert "actions/upload-artifact@v4" in text
    assert "artifacts/parsing_proof_broader_nightly/summary.json" in text
    assert "artifacts/parsing_proof_broader_nightly/gate.json" in text
    assert "artifacts/parsing_proof_broader_nightly/diff.json" in text
    assert "artifacts/parsing_proof_broader_nightly/diff.md" in text
