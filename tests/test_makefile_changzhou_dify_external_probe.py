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


def test_changzhou_gov_plugin_chunk_report_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-gov-plugin-chunk-report",
            "CHANGZHOU_GOV_PLUGIN_DIR=/tmp/plugin",
            "CHANGZHOU_GOV_PLUGIN_SAMPLE=/tmp/sample.json",
            "CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT=/tmp/report.json",
            "CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_MD=/tmp/report.md",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_plugin_chunk_report.py" in command
    assert '--plugin-dir "/tmp/plugin"' in command
    assert '--input "/tmp/sample.json"' in command
    assert '--json-out "/tmp/report.json"' in command
    assert '--markdown-out "/tmp/report.md"' in command


def test_changzhou_gov_plugin_chunk_evidence_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-gov-plugin-chunk-evidence",
            "CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT=/tmp/report.json",
            "CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_OUT=/tmp/evidence.json",
            "CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_MD=/tmp/evidence.md",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_plugin_chunk_evidence.py" in command
    assert '--input "/tmp/report.json"' in command
    assert '--json-out "/tmp/evidence.json"' in command
    assert '--markdown-out "/tmp/evidence.md"' in command


def test_changzhou_gov_plugin_test_report_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-gov-plugin-test-report",
            "CHANGZHOU_GOV_PLUGIN_DIR=/tmp/plugin",
            "CHANGZHOU_GOV_PLUGIN_SAMPLE=/tmp/sample.json",
            "CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT=/tmp/test-report.json",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/pipeline_plugin_runner.py test" in command
    assert '"/tmp/plugin"' in command
    assert '--input "/tmp/sample.json"' in command
    assert "--stage governance" in command
    assert "--stage chunk" in command
    assert "--stage kg" in command
    assert "--no-write-report" in command
    assert '>"/tmp/test-report.json"' in command


def test_changzhou_gov_plugin_test_evidence_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-gov-plugin-test-evidence",
            "CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT=/tmp/test-report.json",
            "CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_OUT=/tmp/test-evidence.json",
            "CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_MD=/tmp/test-evidence.md",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_plugin_test_evidence.py" in command
    assert '--input "/tmp/test-report.json"' in command
    assert '--json-out "/tmp/test-evidence.json"' in command
    assert '--markdown-out "/tmp/test-evidence.md"' in command


def test_changzhou_gov_plugin_corpus_closed_loop_smoke_target_is_explicit_and_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-gov-plugin-corpus-closed-loop-smoke",
            "CHANGZHOU_DIFY_MIMIRQ_BASE_URL=http://192.0.2.6:8000",
            "CHANGZHOU_GOV_CORPUS_SOURCE_DIR=/tmp/gov-corpus",
            "CHANGZHOU_GOV_CORPUS_DATASET_ID=dataset-1",
            "CHANGZHOU_GOV_PLUGIN_REF=plugin:demo-runtime-plugin@1.0.0:chunk",
            "CHANGZHOU_GOV_CORPUS_REPORT_OUT=/tmp/corpus-raw.json",
            "CHANGZHOU_GOV_CORPUS_MAX_FILES=2",
            "CHANGZHOU_GOV_CORPUS_UPLOAD_BATCH_SIZE=1",
            "CHANGZHOU_GOV_CORPUS_EXTENSIONS=.txt,.docx",
            "CHANGZHOU_GOV_CORPUS_REGRESSION_TOP_K=5",
            "CHANGZHOU_GOV_CORPUS_HTTP_TIMEOUT=600",
            "CHANGZHOU_GOV_CORPUS_EXTRA_ARGS=--include-source-root-name --overwrite-goldens",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "Set CHANGZHOU_GOV_CORPUS_SOURCE_DIR=" in command
    assert "scripts/plugin_corpus_closed_loop_smoke.py" in command
    assert '--base-url "http://192.0.2.6:8000"' in command
    assert '--source-dir "/tmp/gov-corpus"' in command
    assert '--dataset-id "dataset-1"' in command
    assert '--plugin-ref "plugin:demo-runtime-plugin@1.0.0:chunk"' in command
    assert '--extensions ".txt,.docx"' in command
    assert "--max-files 2" in command
    assert "--upload-batch-size 1" in command
    assert "--regression-top-k 5" in command
    assert "--timeout 600" in command
    assert "--include-source-root-name --overwrite-goldens" in command
    assert '>"/tmp/corpus-raw.json"' in command


def test_changzhou_gov_plugin_corpus_closed_loop_evidence_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-gov-plugin-corpus-closed-loop-evidence",
            "CHANGZHOU_GOV_CORPUS_REPORT_OUT=/tmp/corpus-raw.json",
            "CHANGZHOU_GOV_CORPUS_EVIDENCE_OUT=/tmp/corpus-evidence.json",
            "CHANGZHOU_GOV_CORPUS_EVIDENCE_MD=/tmp/corpus-evidence.md",
            "CHANGZHOU_GOV_CORPUS_MIN_RETRIEVAL_RECALL=0.95",
            "CHANGZHOU_GOV_CORPUS_MIN_RETRIEVAL_HIT_AT_3=0.75",
            "CHANGZHOU_GOV_CORPUS_MIN_EXPECTED_METADATA_HIT_RATE=0.9",
            "CHANGZHOU_GOV_CORPUS_MIN_EXPECTED_METADATA_RECALL=0.85",
            "CHANGZHOU_GOV_CORPUS_MIN_CITATION_ACCURACY=0.7",
            "CHANGZHOU_GOV_CORPUS_MIN_CITATION_COVERAGE=0.95",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/plugin_corpus_closed_loop_evidence.py" in command
    assert '--input "/tmp/corpus-raw.json"' in command
    assert '--json-out "/tmp/corpus-evidence.json"' in command
    assert '--markdown-out "/tmp/corpus-evidence.md"' in command
    assert "--min-retrieval-recall 0.95" in command
    assert "--min-retrieval-hit-at-3 0.75" in command
    assert "--min-expected-metadata-hit-rate 0.9" in command
    assert "--min-expected-metadata-recall 0.85" in command
    assert "--min-citation-accuracy 0.7" in command
    assert "--min-citation-coverage 0.95" in command


def test_changzhou_gov_delivery_pack_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-gov-delivery-pack",
            "CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT=/tmp/plugin.json",
            "CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_MD=/tmp/plugin.md",
            "CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_OUT=/tmp/plugin-evidence.json",
            "CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_MD=/tmp/plugin-evidence.md",
            "CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT=/tmp/plugin-test.json",
            "CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_OUT=/tmp/plugin-test-evidence.json",
            "CHANGZHOU_DIFY_READINESS_OUT=/tmp/readiness.json",
            "CHANGZHOU_DIFY_READINESS_EVIDENCE_OUT=/tmp/readiness.md",
            "CHANGZHOU_DIFY_READINESS_AUDIT_OUT=/tmp/readiness-audit.json",
            "CHANGZHOU_GOV_DELIVERY_PACK_OUT=/tmp/pack.json",
            "CHANGZHOU_GOV_DELIVERY_PACK_MD=/tmp/pack.md",
            "CHANGZHOU_GOV_DELIVERY_PACK_MAX_READINESS_AGE_MINUTES=45",
            "CHANGZHOU_GOV_DELIVERY_PACK_REQUIRE_READINESS_AUDIT=1",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_delivery_pack.py" in command
    assert '--plugin-report "/tmp/plugin.json"' in command
    assert '--plugin-chunk-evidence "/tmp/plugin-evidence.json"' in command
    assert '--plugin-chunk-evidence-markdown "/tmp/plugin-evidence.md"' in command
    assert '--plugin-test-report "/tmp/plugin-test.json"' in command
    assert '--plugin-test-evidence "/tmp/plugin-test-evidence.json"' in command
    assert "--plugin-markdown" not in command
    assert '--readiness-summary "/tmp/readiness.json"' in command
    assert '--readiness-evidence "/tmp/readiness.md"' in command
    assert '--readiness-audit "/tmp/readiness-audit.json"' in command
    assert "--require-readiness-audit-persisted" in command
    assert "--max-readiness-age-minutes 45" in command
    assert '--json-out "/tmp/pack.json"' in command
    assert '--markdown-out "/tmp/pack.md"' in command


def test_changzhou_dify_readiness_gate_quiet_redirects_raw_output_to_log() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-readiness-gate-quiet",
            "CHANGZHOU_DIFY_READINESS_LOG=/tmp/readiness.log",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "changzhou-dify-readiness-gate" in command
    assert '>"/tmp/readiness.log" 2>&1' in command
    assert "changzhou-dify-readiness-status" in command
    assert "Readiness raw log: /tmp/readiness.log" in command


def test_changzhou_gov_delivery_pack_refresh_runs_quiet_gate_before_pack() -> None:
    result = subprocess.run(
        ["make", "-n", "changzhou-gov-delivery-pack-refresh"],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    quiet_index = command.index('changzhou-dify-readiness-gate >"')
    pack_index = command.index("scripts/changzhou_gov_delivery_pack.py")
    assert quiet_index < pack_index


def test_changzhou_gov_delivery_pack_refresh_does_not_run_live_corpus_smoke() -> None:
    result = subprocess.run(
        ["make", "-n", "changzhou-gov-delivery-pack-refresh"],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/plugin_corpus_closed_loop_smoke.py" not in command
    assert "scripts/plugin_corpus_closed_loop_evidence.py" not in command


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
            "CHANGZHOU_DIFY_MIMIRQ_BASE_URL=http://192.0.2.6:8000",
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
    assert '--base-url "http://192.0.2.6:8000"' in command
    assert '--env-file "/tmp/custom.env"' in command
    assert "--top-k 7" in command
    assert "--timeout 13" in command
    assert '--out "/tmp/direct.json"' in command
    assert "--min-hit-at-3 0.8" in command
    assert "--token" not in command
    assert "DIFY_EXTERNAL_KNOWLEDGE_API_KEY" not in command


def test_changzhou_dify_mimirq_direct_kg_mode_targets_are_overridable_without_token() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-mimirq-direct-kg-on-gate",
            "CHANGZHOU_DIFY_CASES=/tmp/custom_cases.json",
            "CHANGZHOU_DIFY_MIMIRQ_BASE_URL=http://192.0.2.6:8000",
            "CHANGZHOU_DIFY_MIMIRQ_ENV_FILE=/tmp/custom.env",
            "CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_ON_OUT=/tmp/kg-on.json",
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
    assert '--base-url "http://192.0.2.6:8000"' in command
    assert '--env-file "/tmp/custom.env"' in command
    assert "--top-k 7" in command
    assert "--timeout 13" in command
    assert "--kg-mode on" in command
    assert '--out "/tmp/kg-on.json"' in command
    assert "--min-hit-at-3 0.8" in command
    assert "--token" not in command
    assert "DIFY_EXTERNAL_KNOWLEDGE_API_KEY" not in command


def test_changzhou_dify_kg_on_off_gate_generates_reports_before_compare() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-kg-on-off-gate",
            "CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_OFF_OUT=/tmp/kg-off.json",
            "CHANGZHOU_DIFY_MIMIRQ_DIRECT_KG_ON_OUT=/tmp/kg-on.json",
            "CHANGZHOU_DIFY_KG_COMPARE_OUT=/tmp/kg-compare.json",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    off_index = command.index("changzhou-dify-mimirq-direct-kg-off-gate")
    on_index = command.index("changzhou-dify-mimirq-direct-kg-on-gate")
    compare_index = command.index("changzhou-dify-kg-compare-gate")
    assert off_index < on_index < compare_index
    assert "CHANGZHOU_DIFY_KG_BASELINE_REPORT=\"/tmp/kg-off.json\"" in command
    assert "CHANGZHOU_DIFY_KG_CANDIDATE_REPORT=\"/tmp/kg-on.json\"" in command
    assert "CHANGZHOU_DIFY_KG_COMPARE_OUT=\"/tmp/kg-compare.json\"" in command


def test_changzhou_dify_workflow_lint_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-workflow-lint",
            "CHANGZHOU_DIFY_APP_ID=app-1",
            "CHANGZHOU_DIFY_CASES=/tmp/custom_cases.json",
            "CHANGZHOU_DIFY_WORKFLOW_LINT_OUT=/tmp/workflow_lint.json",
            "CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT=/tmp/workflow_sanitized.json",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_dify_workflow_lint.py" in command
    assert '--app-id "app-1"' in command
    assert '--storage-state "/tmp/dify_console_storage_state.json"' in command
    assert '--cases "/tmp/custom_cases.json"' in command
    assert "--preflight-gate" in command
    assert '--out "/tmp/workflow_lint.json"' in command
    assert '--patched-workflow-out "/tmp/workflow_sanitized.json"' in command


def test_changzhou_dify_workflow_sync_dry_run_target_is_overridable_without_apply() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-workflow-sync-dry-run",
            "CHANGZHOU_DIFY_APP_ID=app-1",
            "CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT=/tmp/workflow_sanitized.json",
            "CHANGZHOU_DIFY_WORKFLOW_BACKUP_OUT=/tmp/workflow_backup.json",
            "CHANGZHOU_DIFY_WORKFLOW_PAYLOAD_OUT=/tmp/workflow_payload.json",
            "CHANGZHOU_DIFY_WORKFLOW_SYNC_OUT=/tmp/workflow_sync.json",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_dify_workflow_sync.py" in command
    assert '--app-id "app-1"' in command
    assert '--workflow-json "/tmp/workflow_sanitized.json"' in command
    assert '--storage-state "/tmp/dify_console_storage_state.json"' in command
    assert '--backup-out "/tmp/workflow_backup.json"' in command
    assert '--payload-out "/tmp/workflow_payload.json"' in command
    assert '--out "/tmp/workflow_sync.json"' in command
    assert "--apply" not in command


def test_changzhou_dify_workflow_sync_apply_target_is_explicit() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-workflow-sync-apply",
            "CHANGZHOU_DIFY_APP_ID=app-1",
            "CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT=/tmp/workflow_sanitized.json",
            "CHANGZHOU_DIFY_WORKFLOW_SYNC_OUT=/tmp/workflow_sync_apply.json",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_dify_workflow_sync.py" in command
    assert '--app-id "app-1"' in command
    assert '--workflow-json "/tmp/workflow_sanitized.json"' in command
    assert '--out "/tmp/workflow_sync_apply.json"' in command
    assert "--apply" in command


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


def test_changzhou_dify_readiness_evidence_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-readiness-evidence",
            "CHANGZHOU_DIFY_READINESS_OUT=/tmp/readiness.json",
            "CHANGZHOU_DIFY_READINESS_EVIDENCE_OUT=/tmp/evidence.md",
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
    assert '--markdown-out "/tmp/evidence.md"' in command
    assert '--console-ui-base-url "https://example.test/brainai"' in command
    assert '--app-id "app-1"' in command


def test_changzhou_dify_readiness_persist_audit_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-readiness-persist-audit",
            "CHANGZHOU_DIFY_READINESS_OUT=/tmp/readiness.json",
            "CHANGZHOU_DIFY_MIMIRQ_BASE_URL=http://mimirq.test",
            "CHANGZHOU_GOV_CORPUS_DATASET_ID=00000000-0000-0000-0000-000000000123",
            "CHANGZHOU_DIFY_READINESS_AUDIT_OUT=/tmp/persisted-audit.json",
            "MIMIRQ_TENANT_ID=tenant-1",
            "MIMIRQ_ACCOUNT_ID=account-1",
            "MIMIRQ_USER_ID=user-1",
            "MIMIRQ_API_TOKEN=token-1",
            "MIMIRQ_API_TIMEOUT=13",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/persist_retrieval_audit_snapshot.py" in command
    assert '--summary "/tmp/readiness.json"' in command
    assert '--base-url "http://mimirq.test"' in command
    assert '--dataset-id "00000000-0000-0000-0000-000000000123"' in command
    assert '--tenant-id "tenant-1"' in command
    assert '--account-id "account-1"' in command
    assert '--user-id "user-1"' in command
    assert '--bearer "token-1"' in command
    assert "--timeout 13" in command
    assert "--verify-report" in command
    assert '--out "/tmp/persisted-audit.json"' in command


def test_changzhou_dify_kg_compare_gate_target_is_overridable() -> None:
    result = subprocess.run(
        [
            "make",
            "-n",
            "changzhou-dify-kg-compare-gate",
            "CHANGZHOU_DIFY_KG_BASELINE_REPORT=/tmp/kg-off.json",
            "CHANGZHOU_DIFY_KG_CANDIDATE_REPORT=/tmp/kg-on.json",
            "CHANGZHOU_DIFY_KG_COMPARE_OUT=/tmp/kg-compare.json",
            "CHANGZHOU_DIFY_KG_COMPARE_EXTRA_ARGS=--quality-profile changzhou-retrieval --max-quality-drop 0.01",
        ],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    command = result.stdout
    assert "scripts/changzhou_gov_golden_eval.py" in command
    assert '--baseline-report "/tmp/kg-off.json"' in command
    assert '--candidate-report "/tmp/kg-on.json"' in command
    assert '--out "/tmp/kg-compare.json"' in command
    assert "--quality-profile changzhou-retrieval --max-quality-drop 0.01" in command


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
            "CHANGZHOU_DIFY_KG_COMPARE_OUT=/tmp/kg-compare.json",
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
    assert '--trace-timeout "15"' in command
    assert '--external-probe "/tmp/probe.json"' in command
    assert '--console-auth "/tmp/auth.json"' in command
    assert '--mimirq-direct "/tmp/direct.json"' in command
    assert '--kg-compare "/tmp/kg-compare.json"' in command
    assert '--full-summary "/tmp/full_gate_summary.json"' in command
    assert "--min-hit-at-3 0.8" in command
    assert "--min-generated-answer-grounding-rate 0.9" in command
    assert "--min-generated-answer-key-point-recall 0.9" in command
