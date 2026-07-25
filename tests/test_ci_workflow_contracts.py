import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _assert_uses_self_hosted_bootstrap(workflow: str, command: str, *, count: int) -> None:
    assert workflow.count(command) == count
    assert "python3.11/python3 not found on self-hosted runner" not in workflow
    assert 'if [ -d "$PY_BIN" ]; then' not in workflow
    assert 'echo "PIP_CACHE_DIR=$PIP_CACHE_DIR_VALUE"' not in workflow


def test_self_hosted_ci_bootstrap_script_contract() -> None:
    script = _read("scripts/prepare_self_hosted_ci.sh")

    assert script.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "--include-torch-wheel-dir" in script
    assert 'PY_BIN="$(command -v python3.11 || command -v python3 || true)"' in script
    assert 'VENV_DIR="${SELF_HOSTED_VENV_DIR:-$RUNNER_TEMP/mimirq-py311}"' in script
    assert 'PIP_CACHE_DIR_VALUE="${PIP_CACHE_DIR:-$RUNNER_TEMP/pip-cache}"' in script
    assert 'TORCH_WHEEL_DIR_VALUE="${TORCH_WHEEL_DIR:-$RUNNER_TEMP/torch-wheels}"' in script
    assert 'echo "$VENV_DIR/bin" >> "$GITHUB_PATH"' in script
    assert 'echo "PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple}"' in script
    assert 'echo "PIP_CACHE_DIR=$PIP_CACHE_DIR_VALUE"' in script
    assert 'echo "TORCH_WHEEL_DIR=$TORCH_WHEEL_DIR_VALUE"' in script
    assert 'echo "NO_PROXY=$NO_PROXY_VALUE"' in script
    assert "/home/user/.local/share/uv" not in script
    assert "/data/actions-runner" not in script
    assert "127.0.0.1:35983" not in script


def test_main_ci_runs_database_migrations_and_integrations() -> None:
    workflow = _read(".github/workflows/ci.yml")
    conftest = _read("tests/conftest.py")

    assert "MIMIRQ_INTEGRATION_TESTS: \"1\"" in workflow
    assert "make db-upgrade" in workflow
    assert "tests/test_alembic_upgrade_from_prior_revision.py" in workflow
    assert "tests/test_core_schema_integration.py" in workflow
    assert "tests/test_document_version_diff_integration.py" in workflow
    assert "tests/test_document_versions_integration.py" in workflow
    assert "Base.metadata.create_all" not in conftest


def test_repo_checks_enforce_api_type_drift_and_shared_python_audit_policy() -> None:
    makefile = _read("Makefile")
    security_workflow = _read(".github/workflows/security.yml")
    python_audit = makefile.split("audit-py:", 1)[1].split("audit-web:", 1)[0]

    assert (
        "node web/scripts/check-api-types-drift.mjs --strict "
        "--baseline web/scripts/api-types-drift-baseline.json"
    ) in makefile
    assert "make audit-py" in security_workflow
    assert "--no-deps" not in python_audit
    for advisory in (
        "PYSEC-2026-311",
        "PYSEC-2026-3046",
        "PYSEC-2026-2447",
        "PYSEC-2026-1325",
    ):
        assert f"--ignore-vuln {advisory}" in python_audit


def test_dependency_audit_covers_web_and_handbook_with_shared_policy() -> None:
    makefile = _read("Makefile")
    powershell_audit = _read("scripts/audit.ps1")
    security_workflow = _read(".github/workflows/security.yml")

    assert "audit-docs:" in makefile
    assert "pnpm --dir web audit --prod --audit-level high" in makefile
    assert "scripts/check_pnpm_audit.py" in makefile
    assert "--ignore-registry-errors" not in makefile
    assert "npm audit --audit-level=high" in makefile
    assert "npm audit --omit=dev" not in makefile
    assert "$(MAKE) audit-web" in makefile
    assert "$(MAKE) audit-docs" in makefile
    assert "run: make audit-web" in security_workflow
    assert "run: make audit-docs" in security_workflow
    assert "npm --prefix docs-site audit --audit-level=high" in powershell_audit
    assert powershell_audit.count("Assert-AuditSucceeded") == 5


def test_main_ci_runs_all_browser_smoke_specs_and_critical_coverage() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "make test-web-e2e" in workflow
    assert "pnpm run test:coverage:critical" in workflow


def test_main_ci_host_browser_smoke_stays_on_the_live_stack_spec_in_non_pr_jobs() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "README host browser smoke" in workflow
    assert "pnpm exec playwright test e2e/live-stack.smoke.spec.ts" in workflow
    retrieval_regression_job = workflow.split("\n  retrieval-regression-gate:\n", 1)[1].split(
        "\n  kg-search-regression-gate:\n",
        1,
    )[0]
    assert "if: github.event_name != 'pull_request'" in retrieval_regression_job
    assert 'AUTH_MODE: header' in retrieval_regression_job
    assert "README host browser smoke" in retrieval_regression_job
    assert "NEXT_PUBLIC_USER_ID: ci-bot" in retrieval_regression_job
    assert "NEXT_PUBLIC_TENANT_ID: 00000000-0000-0000-0000-000000000000" in retrieval_regression_job
    assert "pnpm exec playwright test e2e/live-stack.smoke.spec.ts" in retrieval_regression_job


def test_main_ci_uploads_the_generated_test_inventory() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "make test-matrix" in workflow
    assert "name: full-stack-test-inventory" in workflow
    assert "artifacts/test-coverage-matrix.json" in workflow
    assert "artifacts/test-coverage-matrix.md" in workflow
    assert "if-no-files-found: error" in workflow


def test_main_ci_routes_public_prs_to_hosted_smoke_checks() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "permissions:\n  contents: read" in workflow
    assert "SELF_HOSTED_PYTHON_BIN: ${{ vars.CI_SELF_HOSTED_PYTHON_BIN || '' }}" in workflow
    assert "SELF_HOSTED_VENV_DIR: ${{ vars.CI_SELF_HOSTED_VENV_DIR || '' }}" in workflow
    assert "PIP_INDEX_URL: ${{ vars.CI_PIP_INDEX_URL || 'https://pypi.org/simple' }}" in workflow
    assert "PIP_CACHE_DIR: ${{ vars.CI_PIP_CACHE_DIR || '' }}" in workflow
    assert "TORCH_WHEEL_DIR: ${{ vars.CI_TORCH_WHEEL_DIR || '' }}" in workflow
    assert "SELF_HOSTED_HTTP_PROXY: ${{ vars.CI_HTTP_PROXY || '' }}" in workflow
    assert "SELF_HOSTED_HTTPS_PROXY: ${{ vars.CI_HTTPS_PROXY || '' }}" in workflow
    assert "SELF_HOSTED_NO_PROXY: ${{ vars.CI_NO_PROXY || '' }}" in workflow
    _assert_uses_self_hosted_bootstrap(
        workflow,
        "bash scripts/prepare_self_hosted_ci.sh --include-torch-wheel-dir",
        count=4,
    )
    assert "runner.name == 'mimirq-main-01'" not in workflow
    assert "/home/user/.local/share/uv" not in workflow
    assert "/data/actions-runner" not in workflow
    assert "127.0.0.1:35983" not in workflow
    assert "public-pr-verify:" in workflow
    assert "if: github.event_name == 'pull_request'" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "python ci/download_verified_wheels.py --cache-dir \"$TORCH_WHEEL_DIR\"" in workflow
    assert "command -v rg" in workflow
    assert "rg --version | head -n 1" in workflow
    assert "make openapi-check" in workflow
    assert "cp .env.example .env" in workflow
    assert "docker compose --env-file .env -f docker/docker-compose.yml config --quiet" in workflow
    assert "docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.web.yml config --quiet" in workflow
    assert "docker run --rm -v \"$PWD:/work\" -w /work alpine/helm@sha256:aef9b56f64e866207d9591d0abd8f6d767b36aadd12edf68f8a719716d9d29c9 lint deploy/helm/mimirq" in workflow
    assert "template mimirq deploy/helm/mimirq >/dev/null" in workflow
    assert "make test" in workflow
    assert "PR bounded hybrid RAG quality gate" in workflow
    assert "scripts/run_sample_retrieval_benchmark.py" in workflow
    assert "scripts/build_rag_quality_gate_artifacts.py" in workflow
    assert "data/sample/retrieval_fixture_hybrid_v1.json" in workflow
    assert "--retrieval-mode hybrid" in workflow
    assert "tests/rag/evaluation/test_rag_quality_gate.py" in workflow
    assert "make verify" in workflow
    assert "make test-web" in workflow
    assert "pnpm run build" in workflow
    assert "HTTP_PROXY: ${{ vars.CI_HTTP_PROXY || '' }}" in workflow
    assert "HTTPS_PROXY: ${{ vars.CI_HTTPS_PROXY || '' }}" in workflow
    assert "NO_PROXY: ${{ vars.CI_NO_PROXY != '' && format('127.0.0.1,localhost,{0}', vars.CI_NO_PROXY) || '127.0.0.1,localhost' }}" in workflow
    for job in (
        "test-and-verify",
        "docker-build",
        "retrieval-only-bounded-gate",
        "retrieval-regression-gate",
        "kg-search-regression-gate",
    ):
        assert f"{job}:\n    if: github.event_name != 'pull_request'" in workflow


def test_pull_request_lint_and_security_jobs_use_hosted_runners() -> None:
    for workflow_path in (
        ".github/workflows/lint-fast.yml",
        ".github/workflows/security.yml",
    ):
        workflow = _read(workflow_path)
        assert "pull_request:" in workflow
        assert "runs-on: ubuntu-latest" in workflow
        assert "runs-on: [self-hosted" not in workflow
        assert "contents: read" in workflow


def test_api_docs_workflow_actually_deploys_pages() -> None:
    workflow = _read(".github/workflows/api-docs.yml")

    assert "pull_request:" in workflow
    assert "SELF_HOSTED_PYTHON_BIN: ${{ vars.CI_SELF_HOSTED_PYTHON_BIN || '' }}" in workflow
    assert "SELF_HOSTED_VENV_DIR: ${{ vars.CI_SELF_HOSTED_VENV_DIR || '' }}" in workflow
    assert "PIP_INDEX_URL: ${{ vars.CI_PIP_INDEX_URL || 'https://pypi.org/simple' }}" in workflow
    assert "PIP_CACHE_DIR: ${{ vars.CI_PIP_CACHE_DIR || '' }}" in workflow
    assert "SELF_HOSTED_HTTP_PROXY: ${{ vars.CI_HTTP_PROXY || '' }}" in workflow
    assert "SELF_HOSTED_HTTPS_PROXY: ${{ vars.CI_HTTPS_PROXY || '' }}" in workflow
    assert "SELF_HOSTED_NO_PROXY: ${{ vars.CI_NO_PROXY || '' }}" in workflow
    _assert_uses_self_hosted_bootstrap(
        workflow,
        "bash scripts/prepare_self_hosted_ci.sh",
        count=1,
    )
    assert "runner.name == 'mimirq-main-01'" not in workflow
    assert "/home/user/.local/share/uv" not in workflow
    assert "/data/actions-runner" not in workflow
    assert "127.0.0.1:35983" not in workflow
    assert "\n  build:\n" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "make api-docs-build-static" in workflow
    assert "actions/configure-pages@" in workflow
    assert "actions/upload-pages-artifact@" in workflow
    assert "actions/deploy-pages@" in workflow


def test_api_docs_pages_actions_are_gated_before_runner_setup() -> None:
    workflow = _read(".github/workflows/api-docs.yml")

    pr_build_job = workflow.split("\n  deploy:\n", 1)[0]
    assert "actions/configure-pages@" not in pr_build_job
    assert "actions/upload-pages-artifact@" not in pr_build_job
    assert "actions/deploy-pages@" not in pr_build_job
    assert "runs-on: [self-hosted" not in pr_build_job
    assert "\n  publish:\n" in workflow
    build_job, publish_job = workflow.split("\n  publish:\n", 1)
    assert "if: github.event_name != 'pull_request'" in build_job
    assert "needs: deploy" in publish_job
    assert "needs.deploy.outputs.pages_enabled == 'true'" in publish_job
    assert "pages: write" not in build_job
    assert "id-token: write" not in build_job
    assert "pages: write" in publish_job
    assert "id-token: write" in publish_job


def test_security_workflow_pins_trufflehog_by_digest() -> None:
    workflow = _read(".github/workflows/security.yml")

    assert (
        "trufflesecurity/trufflehog@sha256:c28ab4a11e01d6fcc10776f65cce015bdf9795f2393cffa2ec0a7c8464ee58b6"
        in workflow
    )


def test_fresh_database_migrations_widen_alembic_revision_storage() -> None:
    migration = _read("alembic/versions/0002_add_kg_relations.py")

    assert "ALTER TABLE alembic_version" in migration
    assert "VARCHAR(255)" in migration


def test_backend_dockerfile_uses_bundled_buildkit_frontend() -> None:
    dockerfile = _read("docker/Dockerfile")

    assert not dockerfile.lstrip().startswith("# syntax=docker/dockerfile:")


def test_cpu_torch_wheels_match_linux_runtime_requirements() -> None:
    requirements = _read("requirements.txt")
    torch_version = re.search(
        r'^torch==([^;]+); platform_system == "Linux"$', requirements, re.MULTILINE
    )
    torchvision_version = re.search(
        r'^torchvision==([^;]+); platform_system == "Linux"$', requirements, re.MULTILINE
    )

    assert torch_version is not None
    assert torchvision_version is not None
    for install_surface in ("docker/Dockerfile", ".github/workflows/ci.yml"):
        content = _read(install_surface)
        assert set(re.findall(r"\btorch-([0-9.]+)\+cpu-", content)) == {
            torch_version.group(1)
        }
        assert set(re.findall(r"\btorchvision-([0-9.]+)\+cpu-", content)) == {
            torchvision_version.group(1)
        }


def test_docker_ci_supports_cold_web_builds() -> None:
    workflow = _read(".github/workflows/ci.yml")
    docker_job = workflow.split("\n  docker-build:", 1)[1].split(
        "\n  retrieval-only-bounded-gate:", 1
    )[0]
    retrieval_compose = _read("docker/docker-compose.retrieval-dev.yml")
    web_dockerfile = _read("web/Dockerfile.prod")

    assert "timeout-minutes: 60" in docker_job
    assert "docker compose -f docker/docker-compose.retrieval-dev.yml config --quiet" in workflow
    assert "target=/root/.local/share/pnpm/store" in web_dockerfile
    assert "https://registry.npmmirror.com" in web_dockerfile
    assert "README docker quickstart smoke" in docker_job
    assert "make up-web" in docker_job
    assert "artifacts/core-e2e.readme-docker.json" in docker_job
    assert "README lite quickstart smoke" in docker_job
    assert "make up-lite" in docker_job
    assert "artifacts/core-e2e.readme-lite.json" in docker_job
    assert "curl --noproxy '*' -fsS http://127.0.0.1:8000/api/v1/health/ready >/dev/null" in docker_job
    assert "Clean up README lite quickstart stack" in docker_job
    assert (
        "docker compose --env-file .env -f docker/docker-compose.lite.yml down -v --remove-orphans"
        in docker_job
    )
    assert "Smoke built backend and web images" in docker_job
    assert "up -d --no-build" in docker_job
    assert "Docker web-proxy and dual-api core smoke" in docker_job
    assert "python scripts/smoke_test.py" in docker_job
    assert "--bootstrap-register" in docker_job
    assert "--web-base-url http://mimirq-web-smoke-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}:3000" in docker_job
    assert "--secondary-base-url http://$api2_name:8000" in docker_job
    assert "artifacts/core-e2e.web-dual-api.json" in docker_job
    assert '--name "$api2_name" --no-deps mimirq-api' in docker_job
    assert "Docker live core release gate" in docker_job
    assert "python scripts/live_core_release_gate.py" in docker_job
    assert "--secondary-base-url http://$api2_name:8000" in docker_job
    assert "AUTH_MODE_RETRIEVAL_DEV: header" in docker_job
    assert 'UPLOAD_DEDUP_ENABLED_RETRIEVAL_DEV: "true"' in docker_job
    assert 'RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED_RETRIEVAL_DEV: "true"' in docker_job
    assert 'RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY_RETRIEVAL_DEV: "3"' in docker_job
    assert 'RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY_RETRIEVAL_DEV: "3"' in docker_job
    assert "if: always()" in docker_job
    assert "image: ${MIMIRQ_BACKEND_IMAGE:-mimirq-backend}" in retrieval_compose
    assert "RETRIEVAL_CANDIDATE_CACHE_ENABLED_RETRIEVAL_DEV:-false" in retrieval_compose
    assert "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED_RETRIEVAL_DEV:-true" in retrieval_compose
    assert "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY_RETRIEVAL_DEV:-3" in retrieval_compose
    assert "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY_RETRIEVAL_DEV:-3" in retrieval_compose


def test_main_ci_runs_core_e2e_against_the_existing_host_backend() -> None:
    workflow = _read(".github/workflows/ci.yml")
    regression_job = workflow.split("\n  retrieval-regression-gate:", 1)[1].split(
        "\n  kg-search-regression-gate:", 1
    )[0]

    assert "README host web contract smoke" in regression_job
    assert "node web/scripts/api-ping.mjs" in regression_job
    assert "NEXT_PUBLIC_API_URL: http://127.0.0.1:8000" in regression_job
    assert "Install web deps" in regression_job
    assert "pnpm install --frozen-lockfile" in regression_job
    assert "Install Playwright browsers for host browser smoke" in regression_job
    assert "README host browser smoke" in regression_job
    assert 'PLAYWRIGHT_USE_PROD_SERVER: "1"' in regression_job
    assert "pnpm exec playwright test e2e/live-stack.smoke.spec.ts" in regression_job
    assert "README host quickstart smoke" in regression_job
    assert "make core-e2e" in regression_job
    assert "CORE_E2E_BASE_URL=http://127.0.0.1:8000" in regression_job
    assert "CORE_E2E_OUT=artifacts/core-e2e.retrieval-regression.json" in regression_job


def test_live_browser_smoke_never_bootstraps_a_persistent_admin() -> None:
    live_spec = _read("web/e2e/live-stack.smoke.spec.ts")

    assert "PLAYWRIGHT_LIVE_IDENTIFIER" in live_spec
    assert "PLAYWRIGHT_LIVE_PASSWORD" in live_spec
    assert "JWT live smoke requires" in live_spec
    assert "getByRole('button', { name: '首次设置' })" not in live_spec


def test_dockerfiles_bypass_broken_docker_hub_mirror() -> None:
    backend_dockerfile = _read("docker/Dockerfile")
    web_dockerfile = _read("web/Dockerfile.prod")

    assert re.search(
        r"^ARG PYTHON_BASE_IMAGE=public\.ecr\.aws/docker/library/python:3\.11-slim@sha256:[0-9a-f]{64}$",
        backend_dockerfile,
        re.MULTILINE,
    )
    assert "FROM ${PYTHON_BASE_IMAGE} AS base" in backend_dockerfile
    assert re.search(
        r"^ARG NODE_BASE_IMAGE=public\.ecr\.aws/docker/library/node:20-alpine@sha256:[0-9a-f]{64}$",
        web_dockerfile,
        re.MULTILINE,
    )
    assert "FROM ${NODE_BASE_IMAGE} AS base" in web_dockerfile
