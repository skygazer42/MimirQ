import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_changzhou_dify_external_probe_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-external-probe",
            "CHANGZHOU_DIFY_CASES=/tmp/custom_cases.json",
            "CHANGZHOU_DIFY_EXTERNAL_API_ID=external-api-id",
            "CHANGZHOU_DIFY_PROBE_OUT=/tmp/probe.json",
            "CHANGZHOU_DIFY_PROBE_TOP_K=7",
            "CHANGZHOU_DIFY_PROBE_TIMEOUT=13",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_dify_external_knowledge_probe.py" in command
    assert '--cases "/tmp/custom_cases.json"' in command
    assert '--external-api-id "external-api-id"' in command
    assert '--storage-state "/tmp/kingdonsoft_dify_storage_state.json"' in command
    assert "--timeout 13" in command
    assert "--top-k 7" in command
    assert '--out "/tmp/probe.json"' in command
