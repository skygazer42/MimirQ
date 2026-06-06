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
    assert '--storage-state "/tmp/dify_console_storage_state.json"' in command
    assert "--timeout 13" in command
    assert "--top-k 7" in command
    assert '--out "/tmp/probe.json"' in command


def test_changzhou_dify_readiness_gate_runs_probe_before_full_gate() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-readiness-gate",
            "CHANGZHOU_DIFY_CASES=/tmp/custom_cases.json",
            "CHANGZHOU_DIFY_EXTRA_ARGS=--min-hit-at-3 0.8",
            "CHANGZHOU_DIFY_PROBE_OUT=/tmp/probe.json",
            "CHANGZHOU_DIFY_OUT_PREFIX=/tmp/full_gate",
            "CHANGZHOU_DIFY_READINESS_OUT=/tmp/readiness.json",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "set +e" in command
    assert 'rm -f "/tmp/probe.json" "/tmp/full_gate.json" "/tmp/full_gate_answers.json"' in command
    assert '"/tmp/full_gate_eval.json" "/tmp/full_gate_trace.json" "/tmp/full_gate_summary.json" "/tmp/readiness.json"' in command
    assert "make dify-console-check" in command
    assert "auth_rc=$?" in command
    assert "probe_rc=$?" in command
    assert "full_rc=$?" in command
    assert "summary_rc=$?" in command
    auth_index = command.index("scripts/dify_console_login.py")
    probe_index = command.index("scripts/changzhou_gov_dify_external_knowledge_probe.py")
    full_gate_index = command.index("scripts/changzhou_gov_dify_full_gate.py")
    summary_index = command.index("scripts/changzhou_gov_dify_readiness_summary.py")
    assert auth_index < probe_index
    assert probe_index < full_gate_index
    assert full_gate_index < summary_index
    assert '--cases "/tmp/custom_cases.json"' in command
    assert '--out "/tmp/probe.json"' in command
    assert '--external-probe "/tmp/probe.json"' in command
    assert '--full-summary "/tmp/full_gate_summary.json"' in command
    assert "--min-hit-at-3 0.8" in command
    assert "--min-generated-answer-grounding-rate 0.9" in command
    assert "--min-generated-answer-key-point-recall 0.9" in command
