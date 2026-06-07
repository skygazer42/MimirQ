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


def test_changzhou_dify_knowledge_map_check_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-knowledge-map-check",
            "CHANGZHOU_DIFY_KNOWLEDGE_MAP_ENV_FILE=/tmp/custom.env",
            "CHANGZHOU_DIFY_KNOWLEDGE_MAP_OUT=/tmp/map.json",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_dify_knowledge_map_check.py" in command
    assert '--env-file "/tmp/custom.env"' in command
    assert '--out "/tmp/map.json"' in command


def test_changzhou_dify_mimirq_direct_gate_target_is_overridable_without_token_on_command_line() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-mimirq-direct-gate",
            "CHANGZHOU_DIFY_CASES=/tmp/custom_cases.json",
            "CHANGZHOU_DIFY_MIMIRQ_BASE_URL=http://192.168.3.6:8000",
            "CHANGZHOU_DIFY_MIMIRQ_ENV_FILE=/tmp/custom.env",
            "CHANGZHOU_DIFY_MIMIRQ_DIRECT_OUT=/tmp/direct.json",
            "CHANGZHOU_DIFY_MIMIRQ_DIRECT_EXTRA_ARGS=--min-hit-at-3 0.8",
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
    assert "scripts/changzhou_gov_golden_eval.py" in command
    assert '--cases "/tmp/custom_cases.json"' in command
    assert '--base-url "http://192.168.3.6:8000"' in command
    assert '--env-file "/tmp/custom.env"' in command
    assert "--top-k 7" in command
    assert "--timeout 13" in command
    assert '--out "/tmp/direct.json"' in command
    assert "--min-hit-at-3 0.8" in command
    assert "--token" not in command
    assert "DIFY_EXTERNAL_KNOWLEDGE_API_KEY" not in command


def test_dify_console_check_target_writes_report() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "dify-console-check",
            "DIFY_CONSOLE_CHECK_OUT=/tmp/auth.json",
            "DIFY_CONSOLE_MIN_TTL_SECONDS=123",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/dify_console_login.py" in command
    assert "--check" in command
    assert "--min-ttl-seconds 123" in command
    assert '--out "/tmp/auth.json"' in command


def test_dify_console_login_target_writes_report() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "dify-console-login",
            "DIFY_CONSOLE_CHECK_OUT=/tmp/auth.json",
            "DIFY_CONSOLE_MIN_TTL_SECONDS=123",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/dify_console_login.py" in command
    assert '--out "/tmp/auth.json"' in command
    assert "--min-ttl-seconds 123" in command


def test_dify_console_ensure_target_checks_then_can_refresh() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "dify-console-ensure",
            "DIFY_CONSOLE_EMAIL=operator@example.com",
            "DIFY_CONSOLE_PASSWORD_FILE=/tmp/dify-console-password.txt",
            "DIFY_CONSOLE_CHECK_OUT=/tmp/auth.json",
            "DIFY_CONSOLE_MIN_TTL_SECONDS=123",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "make dify-console-check" in command
    assert "make dify-console-login" in command
    assert "Dify console storage state is invalid or expiring; refreshing with configured credentials." in command
    assert '--out "/tmp/auth.json"' in command
    assert "--min-ttl-seconds 123" in command
    assert "operator@example.com" in command
    assert "/tmp/dify-console-password.txt" in command


def test_changzhou_dify_readiness_status_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-readiness-status",
            "CHANGZHOU_DIFY_READINESS_OUT=/tmp/readiness.json",
            "DIFY_CONSOLE_UI_BASE_URL=https://example.test/brainai",
            "CHANGZHOU_DIFY_APP_ID=app-1",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_dify_readiness_status.py" in command
    assert '--summary "/tmp/readiness.json"' in command
    assert '--console-ui-base-url "https://example.test/brainai"' in command
    assert '--app-id "app-1"' in command
    assert "|| true" in command


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
            "CHANGZHOU_DIFY_MIMIRQ_DIRECT_OUT=/tmp/direct.json",
            "CHANGZHOU_DIFY_READINESS_OUT=/tmp/readiness.json",
            "CHANGZHOU_DIFY_KNOWLEDGE_MAP_ENV_FILE=/tmp/custom.env",
            "CHANGZHOU_DIFY_KNOWLEDGE_MAP_OUT=/tmp/map.json",
            "DIFY_CONSOLE_CHECK_OUT=/tmp/auth.json",
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
    assert '"/tmp/map.json"' in command
    assert '"/tmp/direct.json"' in command
    assert '"/tmp/auth.json"' in command
    assert "make changzhou-dify-knowledge-map-check" in command
    assert "make changzhou-dify-mimirq-direct-gate" in command
    assert "make dify-console-ensure" in command
    assert "make dify-console-check" in command
    assert "map_rc=$?" in command
    assert "direct_rc=$?" in command
    assert "auth_rc=$?" in command
    assert "probe_rc=$?" in command
    assert "full_rc=$?" in command
    assert "summary_rc=$?" in command
    map_index = command.index("scripts/changzhou_gov_dify_knowledge_map_check.py")
    direct_index = command.index("scripts/changzhou_gov_golden_eval.py")
    auth_index = command.index("scripts/dify_console_login.py")
    probe_index = command.index("scripts/changzhou_gov_dify_external_knowledge_probe.py")
    full_gate_index = command.index("scripts/changzhou_gov_dify_full_gate.py")
    summary_index = command.index("scripts/changzhou_gov_dify_readiness_summary.py")
    assert map_index < direct_index
    assert direct_index < auth_index
    assert auth_index < probe_index
    assert probe_index < full_gate_index
    assert full_gate_index < summary_index
    assert '--env-file "/tmp/custom.env"' in command
    assert '--out "/tmp/map.json"' in command
    assert '--out "/tmp/direct.json"' in command
    assert '--out "/tmp/auth.json"' in command
    assert '--cases "/tmp/custom_cases.json"' in command
    assert '--out "/tmp/probe.json"' in command
    assert '--external-probe "/tmp/probe.json"' in command
    assert '--console-auth "/tmp/auth.json"' in command
    assert '--mimirq-direct "/tmp/direct.json"' in command
    assert '--full-summary "/tmp/full_gate_summary.json"' in command
    assert "--min-hit-at-3 0.8" in command
    assert "--min-generated-answer-grounding-rate 0.9" in command
    assert "--min-generated-answer-key-point-recall 0.9" in command
