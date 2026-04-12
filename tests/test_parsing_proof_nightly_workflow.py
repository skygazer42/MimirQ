from __future__ import annotations

from pathlib import Path


def test_parsing_proof_nightly_workflow_exists_and_wires_sample_runner() -> None:
    text = Path(".github/workflows/parsing-proof-nightly.yml").read_text(encoding="utf-8")
    artifact_root = "artifacts/parsing_proof_broader_nightly"
    uploaded_surface = (
        "parsing_proof_batch.spec.json",
        "*.fixture.json",
        "*.report.json",
        "summary.json",
        "gate.json",
        "diff.json",
        "diff.md",
    )

    assert "Parsing Proof Nightly" in text
    assert "workflow_dispatch" in text
    assert "schedule" in text
    assert "cron:" in text
    assert "parsing-proof-nightly" in text
    assert "run_sample_parsing_retrieval_proof.py" in text
    assert "actions/upload-artifact@v4" in text
    assert f"--out-dir {artifact_root}" in text

    for artifact_name in uploaded_surface:
        assert f"{artifact_root}/{artifact_name}" in text

    sample_index = text.index("run_sample_parsing_retrieval_proof.py")
    upload_index = text.index("Upload nightly parsing proof artifacts")
    assert sample_index < upload_index
