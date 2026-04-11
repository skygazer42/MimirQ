from __future__ import annotations

from pathlib import Path


def test_parsing_proof_sample_workflow_exists_and_wires_sample_runner() -> None:
    text = Path(".github/workflows/parsing-proof-sample.yml").read_text(encoding="utf-8")
    assert "Parsing Proof Sample" in text
    assert "workflow_dispatch" in text
    assert "run_sample_parsing_retrieval_proof.py" in text
    assert "build_parsing_retrieval_proof_artifacts.py" in text
    assert "parsing_retrieval_proof_gate.py" in text
    assert "ci/parsing_retrieval_proof_thresholds.v1.json" in text
    assert "actions/upload-artifact@v4" in text
    assert "artifacts/parsing_proof_broader_sample/summary.json" in text
    assert "artifacts/parsing_proof_broader_sample/report.json" in text
    assert "artifacts/parsing_proof_broader_sample/gate.json" in text
