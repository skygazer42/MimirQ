import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SILENT_PASS_RE = re.compile(r"except[^\n]*:\n[ \t]*pass\b")

SILENT_PASS_GUARD_PATHS = (
    "app/api/v1/audit.py",
    "app/api/v1/chat.py",
    "app/api/v1/connectors.py",
    "app/api/v1/datasets.py",
    "app/api/v1/evaluations.py",
    "app/api/v1/evidence.py",
    "app/api/v1/ltr.py",
    "app/api/v1/parsing.py",
    "app/api/v1/pipeline.py",
    "app/deepdoc/parser/docling_parser.py",
    "app/deepdoc/parser/excel_parser.py",
    "app/parsing/enrich/image_understanding.py",
    "app/parsing/parsers/deepseek_ocr_parser.py",
    "app/parsing/parsers/email_parser.py",
    "app/parsing/preprocess/image_preprocess.py",
    "app/parsing/preprocess/watermark.py",
    "app/parsing/quality/scorer.py",
    "app/parsing/subprocess_runner.py",
    "app/parsing/subprocess_worker.py",
    "app/parsing/utils/text.py",
    "app/rag/checkpointer/time_travel.py",
    "app/rag/chunking/strategies/llama_index.py",
    "app/rag/core/citations.py",
    "app/rag/embedding/adapter.py",
    "app/rag/engine.py",
    "app/rag/evaluation/ragas.py",
    "app/rag/evaluation/regression_sample_builder.py",
    "app/rag/kg/extraction/extractor.py",
    "app/rag/preprocessing/diagnostics.py",
    "app/rag/preprocessing/processor.py",
    "app/rag/retrieval/orchestrator.py",
    "app/rag/retriever.py",
    "app/rag/workflows/evaluator_optimizer.py",
    "app/services/dataset_precheck_scan_runner.py",
    "app/services/deps_diagnostics_service.py",
    "app/services/evidence_reference_repair_service.py",
    "app/services/indexer.py",
    "app/services/ingestion_run_service.py",
    "app/services/metrics_logger.py",
    "app/services/mineru_service.py",
    "app/services/rag_metrics_dashboard.py",
    "app/services/report_service.py",
    "app/services/retention_jobs.py",
    "app/storage/vector/milvus.py",
    "app/tasks/jobs.py",
    "app/tasks/locks.py",
)

REQUESTS_GUARD_PATHS = (
    "app/deepdoc/parser/mineru_parser.py",
    "app/deepdoc/parser/tcadp_parser.py",
    "app/parsing/enrich/chart_to_data.py",
    "app/parsing/enrich/formula_ocr.py",
    "app/parsing/enrich/vlm_image_caption.py",
    "app/parsing/parsers/mathpix_parser.py",
    "app/parsing/preprocess/deskew.py",
    "app/parsing/preprocess/handwriting_cleanup.py",
    "app/parsing/preprocess/watermark.py",
    "app/services/mineru_service.py",
    "app/third_party/integrated_pipeline/chunkers/naive.py",
)

FULL_SHA_RE = re.compile(r"@[0-9a-f]{40}(?:\s|$)")


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel_path", SILENT_PASS_GUARD_PATHS)
def test_critical_modules_do_not_use_silent_pass_fallbacks(rel_path: str) -> None:
    assert SILENT_PASS_RE.search(_read(rel_path)) is None, rel_path


@pytest.mark.parametrize("rel_path", REQUESTS_GUARD_PATHS)
def test_managed_http_modules_do_not_bypass_shared_clients(rel_path: str) -> None:
    assert "requests." not in _read(rel_path), rel_path


def test_time_context_helpers_do_not_use_naive_datetime_now() -> None:
    assert 'datetime.now().strftime("%Y-%m-%d %H:%M")' not in _read("app/rag/middleware/base.py")
    assert 'datetime.now().strftime("%Y%m%d_%H%M%S")' not in _read("app/deepdoc/parser/tcadp_parser.py")


def test_parser_service_dockerfiles_drop_root_after_install() -> None:
    expected_users = {
        "docker/magicpdf/Dockerfile": "USER appuser",
        "docker/marker/Dockerfile": "USER appuser",
        "docker/olmocr/Dockerfile": "USER appuser",
        "docker/paddlevl/Dockerfile": "USER paddleocr",
        "docker/qianfanocr/Dockerfile": "USER appuser",
    }

    for dockerfile_path, user_line in expected_users.items():
        dockerfile = _read(dockerfile_path)
        assert user_line in dockerfile
        assert dockerfile.rfind(user_line) > dockerfile.rfind("COPY")


def test_sonar_flagged_workflow_actions_are_pinned_to_full_sha() -> None:
    workflow_paths = (
        ".github/workflows/ci.yml",
        ".github/workflows/lint-fast.yml",
        ".github/workflows/security.yml",
    )
    flagged_actions = ("pnpm/action-setup", "trufflesecurity/trufflehog")

    for workflow_path in workflow_paths:
        for line in _read(workflow_path).splitlines():
            if line.lstrip().startswith("uses:") and any(action in line for action in flagged_actions):
                assert FULL_SHA_RE.search(line), line


def test_parser_quality_gates_cannot_ignore_complete_regressions() -> None:
    profile = json.loads(_read("ci/parser_strict_profile.v1.json"))
    assert all(0 <= float(value) < 1 for value in profile["thresholds"].values())

    for workflow_path in (
        ".github/workflows/ci.yml",
        ".github/workflows/parsing-proof-nightly.yml",
        ".github/workflows/parsing-proof-sample.yml",
        ".github/workflows/rag-quality-gate.yml",
    ):
        workflow = _read(workflow_path)
        assert "parsing_retrieval_proof_gate.py" in workflow
        assert "gate.json || true" not in workflow

    for workflow_path in (
        ".github/workflows/ci.yml",
        ".github/workflows/parsing-proof-sample.yml",
        ".github/workflows/rag-quality-gate.yml",
    ):
        workflow = _read(workflow_path)
        assert "build_parsing_retrieval_proof_artifacts.py" not in workflow

    ci_workflow = _read(".github/workflows/ci.yml")
    assert "--input-dir tests/fixtures/parsing_golden" in ci_workflow
    assert "--manifest tests/fixtures/parsing_golden/manifest.json" in ci_workflow


def test_self_hosted_workflows_clean_checkout_state() -> None:
    for workflow_path in (
        ".github/workflows/api-docs.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/lint-fast.yml",
        ".github/workflows/security.yml",
    ):
        assert "clean: false" not in _read(workflow_path)


def test_backend_entrypoint_uses_an_explicit_forwarded_proxy_allowlist() -> None:
    entrypoint = _read("docker/start_backend.sh")
    assert ': "${FORWARDED_ALLOW_IPS:=127.0.0.1}"' in entrypoint
    assert '--forwarded-allow-ips "${FORWARDED_ALLOW_IPS}"' in entrypoint


def test_production_helm_example_uses_distributed_runtime_settings() -> None:
    values = yaml.safe_load(_read("deploy/helm/mimirq/examples/values-prod.yaml"))
    assert int(values["api"]["replicas"]) > 1
    extra_env = {str(item["name"]): str(item["value"]).lower() for item in values["api"]["extraEnv"]}
    assert extra_env["RATE_LIMIT_REDIS_ENABLED"] == "true"
    assert extra_env["BM25_INDEX_ENABLED"] == "false"
    assert extra_env["ENV"] == "production"
    assert extra_env["DB_CREATE_ALL_ON_STARTUP"] == "false"
    assert extra_env["DB_RUNTIME_MIGRATIONS_ENABLED"] == "false"
    worker_extra_env = {str(item["name"]): str(item["value"]).lower() for item in values["worker"]["extraEnv"]}
    assert worker_extra_env["ENV"] == "production"
    assert worker_extra_env["DB_CREATE_ALL_ON_STARTUP"] == "false"
    assert worker_extra_env["DB_RUNTIME_MIGRATIONS_ENABLED"] == "false"
    assert values["migrations"]["enabled"] is True
    assert str(values["runtimeGuards"]["environment"]).lower() == "production"
    assert str(values["runtimeGuards"]["vectorBackend"]).lower() == "milvus"
    assert str(values["runtimeGuards"]["minioEnabled"]).lower() == "true"
    assert str(values["runtimeGuards"]["minioDocumentsEnabled"]).lower() == "true"
    assert str(values["runtimeGuards"]["dbCreateAllOnStartup"]).lower() == "false"
    assert str(values["runtimeGuards"]["dbRuntimeMigrationsEnabled"]).lower() == "false"


def test_helm_defaults_keep_single_replica_dev_path_usable() -> None:
    values = yaml.safe_load(_read("deploy/helm/mimirq/values.yaml"))
    assert values["secretEnv"]["ENV"] == "development"
    assert str(values["secretEnv"]["DB_CREATE_ALL_ON_STARTUP"]).lower() == "true"
    assert str(values["secretEnv"]["DB_RUNTIME_MIGRATIONS_ENABLED"]).lower() == "true"
    assert int(values["api"]["replicas"]) == 1
    assert int(values["worker"]["replicas"]) == 1
    assert values["migrations"]["enabled"] is False


def test_helm_runtime_validation_has_fail_fast_guards_for_multi_instance_risks() -> None:
    template = _read("deploy/helm/mimirq/templates/validate-runtime.yaml")
    assert "Distributed MimirQ deployments require ENV=production." in template
    assert "Distributed MimirQ deployments require DB_CREATE_ALL_ON_STARTUP=false." in template
    assert "Distributed MimirQ deployments require DB_RUNTIME_MIGRATIONS_ENABLED=false." in template
    assert "Distributed MimirQ deployments cannot use VECTOR_BACKEND=faiss or VECTOR_BACKEND=chroma." in template
    assert "Distributed MimirQ deployments with local document storage require persistence.uploads.accessModes to include ReadWriteMany." in template
    assert "migrations.enabled=true requires existingSecretName" in template
    assert template.count('"env" .Values.worker.extraEnv') >= 6
    assert "$workerDbCreateAllOnStartup" in template
    assert "$workerDbRuntimeMigrationsEnabled" in template
    assert "$workerVectorBackend" in template
    assert "$workerMinioDocumentsEnabled" in template


def test_helm_env_lookup_helper_uses_helm_supported_string_coercion() -> None:
    helper = _read("deploy/helm/mimirq/templates/_helpers.tpl")
    assert 'printf "%v"' in helper
    assert "str (" not in helper
    assert "str(" not in helper


def test_helm_migration_job_is_a_pre_install_upgrade_hook_backed_by_existing_secret() -> None:
    template = _read("deploy/helm/mimirq/templates/job-migrate.yaml")
    values = yaml.safe_load(_read("deploy/helm/mimirq/values.yaml"))
    assert '"helm.sh/hook": pre-install,pre-upgrade' in template
    assert '"helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded' in template
    assert 'secretRef:' in template
    assert 'name: {{ include "mimirq.secretName" . }}' in template
    assert "{{- toYaml .Values.migrations.command | nindent 12 }}" in template
    assert values["migrations"]["command"][:2] == ["python", "scripts/alembic_cli.py"]


def test_web_production_healthcheck_uses_ipv4_loopback() -> None:
    dockerfile = _read("web/Dockerfile.prod")
    assert "http://127.0.0.1:3000/" in dockerfile
    assert "http://localhost:3000/" not in dockerfile


def test_web_production_image_drops_next_build_cache() -> None:
    dockerfile = _read("web/Dockerfile.prod")
    assert "RUN rm -rf .next_build/cache" in dockerfile
