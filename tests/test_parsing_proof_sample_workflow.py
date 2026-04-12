from __future__ import annotations

from pathlib import Path


def test_parsing_proof_sample_workflow_exists_and_wires_sample_runner() -> None:
    text = Path(".github/workflows/parsing-proof-sample.yml").read_text(encoding="utf-8")
    artifact_root = "artifacts/parsing_proof_broader_sample"
    uploaded_surface = (
        "parsing_proof_batch.spec.json",
        "*.fixture.json",
        "*.report.json",
        "summary.json",
        "gate.json",
        "diff.json",
        "diff.md",
        "review.md",
    )

    assert "Parsing Proof Sample" in text
    assert "workflow_dispatch" in text
    assert "run_sample_parsing_retrieval_proof.py" in text
    assert "build_parsing_retrieval_proof_artifacts.py" in text
    assert "parsing_retrieval_proof_gate.py" in text
    assert "ci/parsing_retrieval_proof_thresholds.v1.json" in text
    assert "actions/upload-artifact@v4" in text
    assert f"--out-dir {artifact_root}" in text
    assert f"--batch-report {artifact_root}/batch.report.json" in text
    assert f"--summary-out {artifact_root}/summary.json" in text
    assert f"--report-out {artifact_root}/report.json" in text
    assert f"--input {artifact_root}/summary.json" in text
    assert f"--out {artifact_root}/gate.json" in text

    for artifact_name in uploaded_surface:
        assert f"{artifact_root}/{artifact_name}" in text

    sample_index = text.index("run_sample_parsing_retrieval_proof.py")
    build_index = text.index("build_parsing_retrieval_proof_artifacts.py")
    gate_index = text.index("parsing_retrieval_proof_gate.py")
    upload_index = text.index("Upload parsing proof artifacts")
    assert sample_index < build_index < gate_index < upload_index
